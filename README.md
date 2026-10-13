# AreaBot — AI Technical Support Assistant

AreaBot is a document-based AI assistant developed to explore how
technical support for HVAC and cooling equipment can be improved using
large language models and document retrieval.

The application provides a web interface for asking technical questions
and managing a knowledge base of product documentation.

## Features

- AI-powered technical question answering
- PDF document upload and knowledge-base management
- OpenAI API integration with document search
- Streaming chat responses
- Conversation session management
- Web interface for chat and document administration

## Tech Stack

- Python
- FastAPI
- OpenAI API and File Search
- HTML, CSS and JavaScript

## Getting Started

1. Clone the repository.
2. Install Python dependencies:

   pip install -r requirements.txt

3. Copy `.env.example` to `.env`.
4. Add your own OpenAI API key to `.env`.
5. Start the FastAPI backend:

   uvicorn backend:app --reload

The application requires an OpenAI API account and may incur API costs.
A document knowledge base must be configured for document-grounded answers.

## Project Status

Portfolio prototype. The application demonstrates an AI-powered technical
support workflow rather than a production-ready customer service system.

The repository excludes API keys, stored conversations and proprietary or
unreviewed PDF documents.

Public deployment would require authentication, additional API and upload
security, and production testing.
