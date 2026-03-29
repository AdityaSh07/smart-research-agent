from datetime import date, timedelta
from pathlib import Path
from typing import List
from langchain_core.messages import SystemMessage, HumanMessage
from agent.state import State
from agent.schemas import RouterDecision, EvidenceItem, EvidencePack, Plan, Task
from agent.prompts import RESEARCH_SYSTEM, ORCH_SYSTEM, WORKER_SYSTEM, DECIDE_IMAGES_SYSTEM, ROUTER_SYSTEM
from agent.schemas import GlobalImagePlan, ImageSpec
from agent.config import llm
import os
import requests
from langgraph.types import Send, interrupt, Command
from agent.utils import _tavily_search, _iso_to_date



def router_node(state: State) -> dict:
    topic = state["topic"]
    decider = llm.with_structured_output(RouterDecision)
    decision = decider.invoke(
        [
            SystemMessage(content=ROUTER_SYSTEM),
            HumanMessage(content=f"Topic: {topic}\nAs-of date: {state['as_of']}"),
        ]
    )

    # Set default recency window based on mode
    if decision.mode == "open_book":
        recency_days = 7
    elif decision.mode == "hybrid":
        recency_days = 45
    else:
        recency_days = 3650

    return {
        "needs_research": decision.needs_research,
        "mode": decision.mode,
        "queries": decision.queries,
        "recency_days": recency_days,
    }

def route_next(state: State) -> str:
    return "research" if state["needs_research"] else "orchestrator"




def research_node(state: State) -> dict:
    queries = (state.get("queries", []) or [])[:10]
    max_results = 6

    raw_results: List[dict] = []
    for q in queries:
        raw_results.extend(_tavily_search(q, max_results=max_results))

    if not raw_results:
        return {"evidence": []}

    extractor = llm.with_structured_output(EvidencePack)
    pack = extractor.invoke(
        [
            SystemMessage(content=RESEARCH_SYSTEM),
            HumanMessage(
                content=(
                    f"As-of date: {state['as_of']}\n"
                    f"Recency days: {state['recency_days']}\n\n"
                    f"Raw results:\n{raw_results}"
                )
            ),
        ]
    )

    # Deduplicate by URL
    dedup = {}
    for e in pack.evidence:
        if e.url:
            dedup[e.url] = e
    evidence = list(dedup.values())

    # HARD RECENCY FILTER for open_book weekly roundup
    # keep only items with a parseable ISO date and within the window.
    mode = state.get("mode", "closed_book")
    if mode == "open_book":
        as_of = date.fromisoformat(state["as_of"])
        cutoff = as_of - timedelta(days=int(state["recency_days"]))
        fresh: List[EvidenceItem] = []
        for e in evidence:
            d = _iso_to_date(e.published_at)
            if d and d >= cutoff:
                fresh.append(e)
        evidence = fresh

    return {"evidence": evidence}



# -----------------------------
# 5) Orchestrator (Plan)
# -----------------------------

def orchestrator_node(state: State) -> dict:
    planner = llm.with_structured_output(Plan)
    evidence = state.get("evidence", [])
    mode = state.get("mode", "closed_book")

    # Force blog_kind for open_book
    forced_kind = "news_roundup" if mode == "open_book" else None

    plan = planner.invoke(
        [
            SystemMessage(content=ORCH_SYSTEM),
            HumanMessage(
                content=(
                    f"Topic: {state['topic']}\n"
                    f"Mode: {mode}\n"
                    f"As-of: {state['as_of']} (recency_days={state['recency_days']})\n"
                    f"{'Force blog_kind=news_roundup' if forced_kind else ''}\n\n"
                    f"Evidence (ONLY use for fresh claims; may be empty):\n"
                    f"{[e.model_dump() for e in evidence][:16]}\n\n"
                    f"Instruction: If mode=open_book, your plan must NOT drift into a tutorial."
                )
            ),
        ]
    )

    # Ensure open_book forces the kind even if model forgets
    if forced_kind:
        plan.blog_kind = "news_roundup"

    return {"plan": plan}




# -----------------------------
# 6) Fanout
# -----------------------------
def fanout(state: State):
    assert state["plan"] is not None
    return [
        Send(
            "each_section_creator",
            {
                "task": task.model_dump(),
                "topic": state["topic"],
                "mode": state["mode"],
                "as_of": state["as_of"],
                "recency_days": state["recency_days"],
                "plan": state["plan"].model_dump(),
                "evidence": [e.model_dump() for e in state.get("evidence", [])],
            },
        )
        for task in state["plan"].tasks
    ]


# -----------------------------
# 7) Creator (write one section)
# -----------------------------


def worker_node(payload: dict) -> dict:
    
    task = Task(**payload["task"])
    plan = Plan(**payload["plan"])
    evidence = [EvidenceItem(**e) for e in payload.get("evidence", [])]
    topic = payload["topic"]
    mode = payload.get("mode", "closed_book")
    as_of = payload.get("as_of")
    recency_days = payload.get("recency_days")

    bullets_text = "\n- " + "\n- ".join(task.bullets)

    # Provide a compact evidence list for citation use
    evidence_text = ""
    if evidence:
        evidence_text = "\n".join(
            f"- {e.title} | {e.url} | {e.published_at or 'date:unknown'}".strip()
            for e in evidence[:20]
        )

    section_md = llm.invoke(
        [
            SystemMessage(content=WORKER_SYSTEM),
            HumanMessage(
                content=(
                    f"Blog title: {plan.blog_title}\n"
                    f"Audience: {plan.audience}\n"
                    f"Tone: {plan.tone}\n"
                    f"Blog kind: {plan.blog_kind}\n"
                    f"Constraints: {plan.constraints}\n"
                    f"Topic: {topic}\n"
                    f"Mode: {mode}\n"
                    f"As-of: {as_of} (recency_days={recency_days})\n\n"
                    f"Section title: {task.title}\n"
                    f"Goal: {task.goal}\n"
                    f"Target words: {task.target_words}\n"
                    f"Tags: {task.tags}\n"
                    f"requires_research: {task.requires_research}\n"
                    f"requires_citations: {task.requires_citations}\n"
                    f"requires_code: {task.requires_code}\n"
                    f"Bullets:{bullets_text}\n\n"
                    f"Evidence (ONLY use these URLs when citing):\n{evidence_text}\n"
                )
            ),
        ]
    ).content.strip()

    # deterministic ordering
    return {"sections": [(task.id, section_md)]}

# -----------------------------
# 8) Review Node (human-in-the-loop)
# -----------------------------
def review_node(state: State) -> dict:
    """Allow human review, approval, and editing of sections before finalization."""
    if not state["sections"]:
        return {"approved_sections": []}
    
    # Organize sections by task_id
    sections_dict = {task_id: md for task_id, md in state["sections"]}
    sorted_ids = sorted(sections_dict.keys())
    
    # Format sections for review
    review_text = "\n" + "=" * 100 + "\n"
    review_text += "SECTION REVIEW - Approve or Edit Before Finalizing\n"
    review_text += "=" * 100 + "\n\n"
    
    for task_id in sorted_ids:
        review_text += f"\n{'─' * 100}\n"
        review_text += f"SECTION {task_id}:\n"
        review_text += f"{sections_dict[task_id]}\n"
    
    review_text += f"\n{'─' * 100}\n\n"
    review_text += "INSTRUCTIONS:\n"
    review_text += "Provide feedback as JSON with 'approved_ids' and optional 'edits' field.\n\n"
    review_text += "EXAMPLES:\n\n"
    review_text += '1. Approve all sections without changes:\n'
    review_text += '   {"approved_ids": ' + str(sorted_ids) + '}\n\n'
    review_text += '2. Approve sections 1, 2 and edit section 3:\n'
    review_text += f'   {{"approved_ids": [1, 2], "edits": {{3: "## New Section Title\\n\\nYour edited content here..."}}}}\n\n'
    review_text += '3. Edit multiple sections (2 and 4) and approve the rest:\n'
    review_text += f'   {{"approved_ids": {sorted_ids}, "edits": {{2: "Edited section 2 content", 4: "Edited section 4 content"}}}}\n\n'
    review_text += '4. Approve only specific sections (reject others):\n'
    review_text += '   {"approved_ids": [1, 3, 5]}\n\n'
    review_text += '5. Edit a section with markdown formatting:\n'
    review_text += '   {"approved_ids": [1, 2, 3], "edits": {2: "## Updated Title\\n\\n- Point 1\\n- Point 2\\n\\nSome detailed text here..."}}\n\n'
    review_text += "NOTES:\n"
    review_text += "- Use 'approved_ids' to specify which sections are approved (can be a subset)\n"
    review_text += "- Use 'edits' to provide replacement text for any section\n"
    review_text += "- For edits, include the full section markdown (including ## heading)\n"
    review_text += "- Sections in 'edits' are automatically added to approved_ids\n"
    review_text += "- Empty 'edits' {} means no changes to approved sections\n"
    
    # Interrupt to get user feedback
    user_feedback = interrupt(review_text)
    
    # Process user feedback
    approved_ids = user_feedback.get("approved_ids", [])
    edits = user_feedback.get("edits", {})
    
    # Sections with edits are automatically approved
    final_approved_ids = set(approved_ids) | set(edits.keys())
    
    # Build approved sections with edits applied
    approved_sections = []
    for task_id in sorted_ids:
        if task_id in final_approved_ids:
            if task_id in edits:
                # Use edited version
                approved_sections.append((task_id, edits[task_id]))
            else:
                # Keep original
                approved_sections.append((task_id, sections_dict[task_id]))
    
    return {"approved_sections": approved_sections}


# ============================================================
# 8) ReducerWithImages (subgraph)
#    merge_content -> decide_images -> generate_and_place_images
# ============================================================
def merge_content(state: State) -> dict:

    plan = state["plan"]

    ordered_sections = [md for _, md in sorted(state["sections"], key=lambda x: x[0])]
    body = "\n\n".join(ordered_sections).strip()
    merged_md = f"# {plan.blog_title}\n\n{body}\n"
    return {"merged_md": merged_md}


def decide_images(state: State) -> dict:
    
    planner = llm.with_structured_output(GlobalImagePlan)
    merged_md = state["merged_md"]
    plan = state["plan"]
    assert plan is not None

    image_plan = planner.invoke(
        [
            SystemMessage(content=DECIDE_IMAGES_SYSTEM),
            HumanMessage(
                content=(
                    f"Blog kind: {plan.blog_kind}\n"
                    f"Topic: {state['topic']}\n\n"
                    "Insert placeholders + propose image prompts.\n\n"
                    f"{merged_md}"
                )
            ),
        ]
    )

    return {
        "md_with_placeholders": image_plan.md_with_placeholders,
        "image_specs": [img.model_dump() for img in image_plan.images],
    }


def _generate_image_bytes(prompt: str) -> bytes:
    
    import base64
    
    api_key = os.environ.get("NVIDIA_API_KEY")
    if not api_key:
        raise RuntimeError("NVIDIA_API_KEY is not set.")
    
    invoke_url = "https://ai.api.nvidia.com/v1/genai/stabilityai/stable-diffusion-3-medium"
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }
    
    payload = {
        "prompt": prompt,
        "cfg_scale": 5,
        "aspect_ratio": "16:9",
        "seed": 0,
        "steps": 50,
        "negative_prompt": ""
    }
    
    response = requests.post(invoke_url, headers=headers, json=payload)
    response.raise_for_status()
    response_body = response.json()
    
    # Extract image from response
    # nvidia model returns base64 encoded image data
    if "image" in response_body:
        image_data = response_body["image"]
        
        if isinstance(image_data, str):
            return base64.b64decode(image_data)
        return image_data
    
    raise RuntimeError(f"No image data in NVIDIA NIM response: {response_body}")


def generate_and_place_images(state: State) -> dict:

    plan = state["plan"]
    assert plan is not None

    md = state.get("md_with_placeholders") or state["merged_md"]
    image_specs = state.get("image_specs", []) or []

    # If no images requested, just write merged markdown
    if not image_specs:
        filename = f"{plan.blog_title}.md"
        Path(filename).write_text(md, encoding="utf-8")
        return {"final": md}

    images_dir = Path("images")
    images_dir.mkdir(exist_ok=True)

    for spec in image_specs:
        placeholder = spec["placeholder"]
        filename = spec["filename"]
        out_path = images_dir / filename

        # generate only if needed
        if not out_path.exists():
            try:
                img_bytes = _generate_image_bytes(spec["prompt"])
                out_path.write_bytes(img_bytes)
            except Exception as e:
                # graceful fallback: keep doc usable
                prompt_block = (
                    f"> **[IMAGE GENERATION FAILED]** {spec.get('caption','')}\n>\n"
                    f"> **Alt:** {spec.get('alt','')}\n>\n"
                    f"> **Prompt:** {spec.get('prompt','')}\n>\n"
                    f"> **Error:** {e}\n"
                )
                md = md.replace(placeholder, prompt_block)
                continue

        img_md = f"![{spec['alt']}](images/{filename})\n*{spec['caption']}*"
        md = md.replace(placeholder, img_md)

    filename = f"{plan.blog_title}.md"
    Path(filename).write_text(md, encoding="utf-8")
    return {"final": md}