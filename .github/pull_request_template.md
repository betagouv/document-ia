# Description

<!-- Describe what this PR changes and why. -->

## Type of change

<!-- Check all that apply. -->

- [ ] New document extraction model
- [ ] Existing document schema update
- [ ] API change
- [ ] Worker change
- [ ] Infrastructure change
- [ ] Evaluation change
- [ ] Documentation
- [ ] Bug fix

## Context

<!-- Link related issue, ticket, specification, or example document if available. -->

- Related issue:
- Related documentation:

## Review Notes

<!-- Anything reviewers should pay special attention to: naming, field semantics, examples, backward compatibility, etc. -->

## New Document Extraction Model

<!-- Fill this section if this PR adds a new document type. Otherwise, remove this section. -->

Document type:

<!-- Example: Carte Grise -->

Purpose:

<!-- Explain what this document proves or what data should be extracted from it. -->

### Document Schema Checklist

<!-- Required when adding or changing a model in document-ia-schemas. -->

- [ ] Added or updated `document-ia-schemas/src/document_ia_schemas/<document_type>.py`
- [ ] Added the document type to `SupportedDocumentType` in `document-ia-schemas/src/document_ia_schemas/__init__.py`
- [ ] Added or updated the Pydantic `<Name>Model` and `<Name>ExtractSchema`
- [ ] Updated `document-ia-schemas/README.md` if the list of supported document types changed
- [ ] Regenerated worker prompt snapshots when schema changes affect extraction prompts
Snapshot regeneration command:
```bash
cd document-ia-worker
poetry run python tests/fixtures/regenerate_extraction_prompt_fixtures.py
```

Reference docs:

- [document-ia-schemas/CONTRIBUTING.md](../document-ia-schemas/CONTRIBUTING.md)
- [document-ia-worker/README.md](../document-ia-worker/README.md)
