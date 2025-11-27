# Contacts App

## Overview
The Contacts app manages personal contact books and enables discovery of public figures, artists, musicians, and other people through web search integration.

## Features

### Contact Book Management
Local management of saved contacts with full profile information and relationship details.

### Public Figure Discovery
Search and learn about public figures, artists, musicians, LinkedIn profiles, and other publicly known people.

## Skills

### Research
**Status**: Planned

Triggers multiple web searches to gather and synthesize information about a person into an embedded preview. The skill performs:

1. **Multiple Web Searches**: Executes parallel web searches using various query patterns to find information about the person across different sources
2. **Information Aggregation**: Consolidates search results from multiple platforms and sources
3. **Preview Generation**: Creates a "contact" embedded preview containing:
   - Overview: Key facts and highlights about the person
   - Summary: Consolidated information from all collected search results
   - Source Attribution: References to where information was gathered

**Use Cases**:
- Research public figures, artists, or musicians before engagement
- Discover professional profiles on LinkedIn and similar platforms
- Verify and gather information about individuals
- Create rich contact previews with aggregated public data
- Build contact profiles with background information

**Data Flow**:
- User initiates research on a person (name or identifier)
- System executes parallel web searches across multiple sources
- Results are collected and processed
- Embedded contact preview is generated and displayed
