Product: FieldMapper — AI-powered city dataset onboarding pipeline

Company context: I2I Tech Solutions is a DBE-certified GovTech data infrastructure firm. Founder is Marvin Lowrance, technical lead with production CDS pipeline delivery at SFMTA and ETL pipeline delivery for OpenGov Minnesota.

Purpose of this tool: Portfolio project and content series demonstrating Claude API and MCP server expertise. Also a real tool that solves a problem Marvin has encountered directly at SFMTA and LADOT — city datasets are messy, non-standard, and hard to onboard.

V1 — Data Dictionary Generator

Core function: User uploads a CSV or JSON dataset → Claude API inspects the schema → outputs a structured data dictionary

Optional: User can upload a target schema (CDS, MDS, GTFS, or custom JSON/CSV). Claude maps each field to the closest match with a confidence score. If no schema provided, Claude maps to best-fit known standard.

UI: Streamlit

Dataset file upload (CSV or JSON)
Optional target schema upload
Generate button
Structured output rendered as table
Download as CSV or JSON
Key output fields per column:

Field name
Inferred data type
Description of what the field likely contains
Suggested standard mapping with confidence note
Data quality notes (nulls, inconsistencies, anomalies)
Stack: Python, Anthropic SDK, Streamlit

Test dataset: Public SF or LA open data transportation dataset

Out of scope for V1: Authentication, database storage, multi-file upload

V2 — MCP Server (Agentic Pipeline)

Core function: Claude autonomously orchestrates a multi-step dataset onboarding pipeline via MCP tools exposed by a custom MCP server

Tools exposed by the MCP server:

Tool	What it does
fetch_dataset(url)	Pulls a dataset from a URL
generate_schema(data)	Inspects data, generates a DB schema
load_to_db(data, schema)	Loads data into the database
execute_pipeline(scripts)	Runs defined transformation scripts on the data
generate_dictionary(data, target_schema)	V1 functionality as a callable tool
How it works: User gives Claude a natural language goal — "ingest this dataset from this URL, create a schema, load it, and run these transformations" — Claude calls the tools in sequence, passes outputs between steps, returns a summary

Stack: Python, Anthropic SDK, MCP SDK, SQLite (v2), PostgreSQL (future)

UI: Streamlit demo layer showing the pipeline steps executing in real time

Out of scope for V2: Multi-tenant, authentication, hosted deployment


GOALS:
Take a sample of data and build a data dictionary