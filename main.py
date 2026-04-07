from __future__ import annotations

from datetime import date
from pathlib import Path
from uuid import uuid4
from typing import Dict, List

from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from langgraph.types import Command

import model as research_agent

# Store session state
sessions: Dict[str, dict] = {}


class GenerateRequest(BaseModel):
    topic: str = Field(..., min_length=4, max_length=240)
    as_of: str | None = None


class GenerateResponse(BaseModel):
    session_id: str
    topic: str
    sections: Dict[int, str]
    plan_title: str


class ReviewFeedback(BaseModel):
    approved_ids: List[int]
    edits: Dict[int, str] = {}


app = FastAPI(
    title="Research Article Agent",
    description="LangGraph-powered research and article/blog generation API.",
    version="1.0.0",
)

BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

images_path = BASE_DIR / "images"
images_path.mkdir(exist_ok=True) # to show img in md
app.mount("/images", StaticFiles(directory=images_path), name="images")

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def run_generation(topic: str, as_of: str | None) -> dict:
    as_of_value = as_of or date.today().isoformat()
    config = {"configurable": {"thread_id": f"web-{uuid4()}"}}

    state = {
        "topic": topic,
        "mode": "",
        "needs_research": False,
        "queries": [],
        "evidence": [],
        "plan": None,
        "as_of": as_of_value,
        "recency_days": 7,
        "sections": [],
        "approved_sections": [],
        "merged_md": "",
        "md_with_placeholders": "",
        "image_specs": [],
        "final": "",
    }

    out = None
    try:
        out = research_agent.app.invoke(state, config=config)
    except Exception as e:
        # Interrupt raises an exception; get the state from it
        if hasattr(e, 'args') and len(e.args) > 0:
            out = e.args[0]
        else:
            out = {}
    
    if out is None:
        out = {}
    
    return out, config


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "engine": "langgraph"}


@app.post("/api/generate", response_model=GenerateResponse)
def generate(payload: GenerateRequest):
    """Start blog generation and return sections for review"""
    try:
        out, config = run_generation(payload.topic.strip(), payload.as_of)
        session_id = str(uuid4())
        
        # Extract sections for review
        sections = {}
        if isinstance(out, dict) and "sections" in out:
            for item in out["sections"]:
                if isinstance(item, (list, tuple)) and len(item) == 2:
                    task_id, section_md = item
                    sections[int(task_id)] = section_md
        
        # Extract plan info
        plan_title = payload.topic
        if isinstance(out.get("plan"), dict):
            plan_title = out["plan"].get("blog_title", payload.topic)
        elif hasattr(out.get("plan"), 'blog_title'):
            plan_title = out["plan"].blog_title
        
        # Store session
        sessions[session_id] = {
            "config": config,
            "topic": payload.topic,
            "as_of": payload.as_of or date.today().isoformat(),
            "sections": sections,
            "plan": out.get("plan"),
            "full_state": out
        }
        
        return GenerateResponse(
            session_id=session_id,
            topic=payload.topic,
            sections=sections,
            plan_title=plan_title,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/blog/session/{session_id}")
def get_session(session_id: str):
    """Get current session state"""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = sessions[session_id]
    return {
        "topic": session["topic"],
        "sections": session["sections"],
        "plan_title": session.get("plan_title", session["topic"]),
        "as_of": session["as_of"]
    }


@app.post("/api/blog/review")
def submit_review(session_id: str = Query(...), feedback: ReviewFeedback = None):
    """Submit review feedback with approved sections and edits"""
    try:
        if session_id not in sessions:
            raise HTTPException(status_code=404, detail="Session not found")
        
        if feedback is None:
            raise HTTPException(status_code=400, detail="No feedback provided")
        
        session = sessions[session_id]
        config = session["config"]
        
        # Log the review submission
        edited_count = len(feedback.edits)
        approved_count = len(feedback.approved_ids)
        
        print(f"Review submitted for session {session_id}:")
        print(f"  - Approved sections: {feedback.approved_ids}")
        print(f"  - Edited sections: {list(feedback.edits.keys())}")
        print(f"  - Total edits: {edited_count}")
        
        # Resume workflow with user feedback
        
        final_out = research_agent.app.invoke(
            Command(resume={
                "approved_ids": feedback.approved_ids,
                "edits": feedback.edits
            }),
            config=config
        )
        
        # Extract final content from the output
        final_md = final_out.get("final", "")
        
        if not final_md:
            raise ValueError("Final markdown generation returned empty content")
        
        # Get blog title for filename
        plan = final_out.get("plan")
        if isinstance(plan, dict):
            plan_title = plan.get("blog_title", "blog")
        elif hasattr(plan, 'blog_title'):
            plan_title = plan.blog_title
        else:
            plan_title = session["topic"]
        
        # Clean filename
        filename = f"{plan_title.replace(' ', '_')}.md"
        
        # Save to file in current directory
        filepath = Path(filename)
        filepath.write_text(final_md, encoding="utf-8")
        
        return {
            "status": "success",
            "final_md": final_md,
            "saved_file": filename
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e)) from e
