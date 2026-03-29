from typing import TypedDict, List, Optional, Annotated
from agent.schemas import EvidenceItem, Plan
import operator



class State(TypedDict):
    topic: str

    # routing / research
    mode: str
    needs_research: bool
    queries: List[str]
    evidence: List[EvidenceItem]
    plan: Optional[Plan]

    # recency control
    as_of: str           
    recency_days: int    # 7 for weekly news, 30 for hybrid

    # workers
    sections: Annotated[List[tuple[int, str]], operator.add]  
    approved_sections: List[tuple[int, str]]  # sections after human review and edits
    
    # reducer/image
    merged_md: str
    md_with_placeholders: str
    image_specs: List[dict]

    final: str
