from __future__ import annotations

from typing import List, Literal, Optional

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from backend.services.figure_extract_service import extract_charts_and_figures
from backend.services.langchain_stack import format_context, get_llm, retrieve_chunks

SchemaType = Literal["projects", "charts", "key_facts", "custom"]

SCHEMA_QUERIES = {
    "projects": "projects work experience research employment portfolio achievements dates",
    "charts": "CHART_DATA figure chart graph pie percentage color segment legend Fig",
    "key_facts": "key findings facts statistics summary conclusions important data",
    "custom": "all information entities facts data tables figures",
}

EXTRACT_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "Extract structured data from document excerpts only. "
            "Do not invent fields not supported by the text. Use null for missing values.",
        ),
        (
            "human",
            "Schema: {schema_name}\n"
            "Instructions: {schema_instructions}\n\n"
            "Document excerpts:\n{context}",
        ),
    ]
)

SCHEMA_INSTRUCTIONS = {
    "projects": "Extract every project, role, or research item with title, date/timeframe, and description.",
    "charts": "Extract every chart with figure_id, chart_type, and all segments (color, category label, percentage).",
    "key_facts": "Extract the most important facts, statistics, and conclusions as bullet items.",
    "custom": "Extract data matching the user-defined field list.",
}


class ProjectItem(BaseModel):
    title: str = Field(description="Project or role title")
    date: Optional[str] = Field(default=None, description="Date or timeframe")
    description: str = Field(description="What was done")


class ProjectsSchema(BaseModel):
    projects: List[ProjectItem]


class ChartSegment(BaseModel):
    figure_id: str = Field(description="e.g. Fig. 4.4.1")
    chart_type: str = Field(description="pie, bar, line, etc.")
    color: str = Field(description="Segment color")
    category: str = Field(description="Legend label / category")
    percentage: str = Field(description="Percentage or value shown")


class ChartsSchema(BaseModel):
    charts: List[ChartSegment]


class KeyFact(BaseModel):
    fact: str = Field(description="Important fact from the document")
    page: Optional[int] = Field(default=None, description="Page number if known")


class KeyFactsSchema(BaseModel):
    key_facts: List[KeyFact]


class CustomField(BaseModel):
    name: str
    value: str


class CustomSchema(BaseModel):
    fields: List[CustomField]


_SCHEMA_MODELS = {
    "projects": ProjectsSchema,
    "charts": ChartsSchema,
    "key_facts": KeyFactsSchema,
    "custom": CustomSchema,
}


def run_structured_extract(
    doc_id: str,
    schema: SchemaType,
    custom_fields: Optional[List[str]] = None,
) -> dict:
    if schema == "charts":
        return extract_charts_and_figures(doc_id)

    query = SCHEMA_QUERIES.get(schema, SCHEMA_QUERIES["custom"])
    chunks = retrieve_chunks(
        query,
        doc_id,
        score_threshold=0.55,
        top_k=12,
    )
    if not chunks:
        return {"error": "No document content found. Re-upload the PDF."}

    model_cls = _SCHEMA_MODELS[schema]
    llm = get_llm().with_structured_output(model_cls)

    instructions = SCHEMA_INSTRUCTIONS[schema]
    if schema == "custom" and custom_fields:
        instructions = f"Extract these fields: {', '.join(custom_fields)}"

    chain = EXTRACT_PROMPT | llm
    result = chain.invoke(
        {
            "schema_name": schema,
            "schema_instructions": instructions,
            "context": format_context(chunks),
        }
    )
    return result.model_dump()
