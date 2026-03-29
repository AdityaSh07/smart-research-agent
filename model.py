from langgraph.graph import StateGraph, START, END
from agent.state import State
from agent.utils import _tavily_search, _iso_to_date
from agent.schemas import Plan, EvidenceItem
from agent.config import llm
from datetime import datetime, timedelta
from agent.nodes import (
    router_node,
    research_node,
    orchestrator_node,
    worker_node,
    review_node,
    merge_content,
    decide_images,
    generate_and_place_images,
    fanout,
    route_next
)
# build reducer subgraph
reducer_graph = StateGraph(State)
reducer_graph.add_node("merge_content", merge_content)
reducer_graph.add_node("decide_images", decide_images)
reducer_graph.add_node("generate_and_place_images", generate_and_place_images)
reducer_graph.add_edge(START, "merge_content")
reducer_graph.add_edge("merge_content", "decide_images")
reducer_graph.add_edge("decide_images", "generate_and_place_images")
reducer_graph.add_edge("generate_and_place_images", END)
reducer_subgraph = reducer_graph.compile()

# -----------------------------
# 10) Build graph
# -----------------------------
g = StateGraph(State)
g.add_node("router", router_node)
g.add_node("research", research_node)
g.add_node("orchestrator", orchestrator_node)
g.add_node("each_section_creator", worker_node)
g.add_node("review", review_node)
g.add_node("reducer", reducer_subgraph)

g.add_edge(START, "router")
g.add_conditional_edges("router", route_next, {"research": "research", "orchestrator": "orchestrator"})
g.add_edge("research", "orchestrator")

g.add_conditional_edges("orchestrator", fanout, ["each_section_creator"])
g.add_edge("each_section_creator", "review")
g.add_edge("review", "reducer")
g.add_edge("reducer", END)

from langgraph.checkpoint.memory import InMemorySaver

checkpointer = InMemorySaver()

app = g.compile(checkpointer=checkpointer)

app