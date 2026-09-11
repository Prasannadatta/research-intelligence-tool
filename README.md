# Research Intelligence Platform

A research intelligence tool for discovering researchers, analyzing publications, exploring grant-linked outputs, and understanding collaboration patterns across institutions, citations, and journals.

The platform combines multiple scholarly data providers behind a unified search and analysis workflow, with canonical author/work identity stored locally in SQLite.

## Easy Setup

**Before you start (install once):** [Git](https://git-scm.com/downloads), [Python 3](https://www.python.org/downloads/) (on Windows, check **Add Python to PATH**), and [Node.js LTS](https://nodejs.org/) (includes npm).

1. **Get the `v2` code**
   - Git: `git clone -b v2 https://github.com/Prasannadatta/research-intelligence-tool.git`
   - Or download the [v2 ZIP](https://github.com/Prasannadatta/research-intelligence-tool/archive/refs/heads/v2.zip) and unzip it.
2. **Run setup once** (double-click in the project folder)
   - Mac: `setup_mac.command`
   - Windows: `setup_windows.bat`
3. **Run start whenever you use the app**
   - Mac: `start_mac.command`
   - Windows: `start_windows.bat`

The start script opens [http://localhost:5173/](http://localhost:5173/). Setup creates `backend/.env` only if it is missing and never overwrites your database. For API keys and developer details, see [Developer Setup](#developer-setup) below.

## What it does

- **Researcher / author discovery** — search by name or ORCID iD across OpenAlex, ORCID, and arXiv
- **Publication analysis** — view, filter, sort, and export an author’s publications or publications shared by multiple authors
- **Grant-linked publication discovery** — find works associated with a grant number
- **Collaboration insights** — metrics, charts, and tables over stored publication data for selected authors
- **Institution, citation, and journal analysis** — affiliation metadata, citation activity, institution networks/partnerships, and Scopus journal metrics (CiteScore, SJR, SNIP) where available

## Current data sources

| Source | Role |
| --- | --- |
| **OpenAlex** | Primary author and publication metadata (names, works, institutions, topics, citations, grants) |
| **ORCID** | Author identity, search, and enrichment; strong cross-provider identity signal |
| **arXiv** | Secondary author/publication source; enrich-only preprint/version overlays on matched OpenAlex works |
| **Scopus / Elsevier** | Journal metrics (CiteScore, SJR, SNIP); optional Abstract Retrieval enrichment of citation/journal fields on existing works; author affiliation enrichment on hover cards |

**ORCID as an identity bridge.** When an ORCID iD matches exactly across providers, the platform links records: **ORCID → exact OpenAlex match → canonical author → OpenAlex publications**. Name similarity alone is never used to merge identities.

## Author Search

- **All Sources** is the default search mode.
- You can also search **OpenAlex**, **ORCID**, or **arXiv** individually.
- **Name search** — find researchers by display name (with optional affiliation hint).
- **Direct ORCID iD search** — paste an ORCID such as `0000-0001-6860-9566` (with or without the `https://orcid.org/` prefix).
- **Exact-ORCID cross-provider linking** — when OpenAlex and ORCID rows share the same ORCID iD, they are linked; duplicate OpenAlex rows are collapsed onto the ORCID-anchored result.
- **Same-name researchers are not merged by name alone** — two different people named “Lin Lin” remain separate unless their ORCID iDs match.
- **Conflicting ORCIDs remain separate** — the platform never merges solely on normalized display name.

## Analyze Authors

From Author Search, select one or more authors and open **Analyze authors**.

- **One author** — that author’s publications.
- **Multiple authors** — publications that include every selected author (intersection / common publications).
- **Sorting and filtering** — by grant, institution, venue, source, date/year, and related facets where supported.
- **Infinite scroll / load-more pagination** — the publications table fetches provider pages incrementally as you scroll.
- **CSV export** — export the full filtered publication set (not only visible rows).
- **Publication exclusions** — exclude specific works from the active analysis set.
- **Author affiliation hover metadata** — hover author names in the table for available author and institution details.

**Performance and corpus statistics**

- Normal table loading fetches provider pages incrementally; the first page renders without waiting for a full provider crawl.
- After OpenAlex coverage is verified complete, Analyze Authors timeline, filter facets, and the publications table prefer the **stored complete corpus** (via background publication-stats jobs). Until then, UI copy may note that early counts are from the currently loaded sample.
- Background jobs may enrich existing OpenAlex works with arXiv preprint/version metadata and Scopus citation/journal fields (DOI / arXiv id match only; never creates duplicate publication rows). Enrichment is cached and does not block first-page table load.
- **CSV export** can collect the full matching corpus according to your active filters.

## Collaboration Insights

Read-only analysis over stored/canonical publication data for the selected authors. Insights filters operate on dashboard data already loaded for the session and **do not trigger live provider crawls**.

Includes:

- Selected-author collaboration metrics
- Collaboration combinations (chart and table)
- Collaboration by year
- Author and institution participation
- Citation activity
- Institution network and institution partnerships
- **Top Journals** with Scopus journal metrics (CiteScore, SJR, SNIP) when Elsevier credentials are configured
- **Background jobs** for large author selections so expensive Insights calculations can run asynchronously

Open Insights from Analyze Authors via **Analysis**.

## Grant Search and Grant Publications

- Search by **grant number** (OpenAlex and arXiv where supported).
- View publications associated with a grant.
- Sort, filter, and paginate grant-linked publication results.
- Results are **provider-aware** (metadata and coverage vary by source).

## Canonical identity and data model

The backend maintains a local identity layer on top of provider data:

- **Canonical authors and works** — stable internal records used for analysis, persistence, and cross-session continuity.
- **Provider records** — per-provider author/work identifiers (OpenAlex, ORCID, arXiv, etc.) attached to canonical entities.
- **Exact provider IDs preferred** — merges and lookups favor exact ORCID iDs and provider-native IDs over fuzzy name matching.
- **ORCID is a strong identity signal** — exact ORCID matches can link ORCID and OpenAlex provider records on the same canonical author.
- **Never merge solely by normalized name** — ambiguous or conflicting identities remain separate.
- **Publication-specific affiliations preferred** — when available, per-publication authorship affiliations are preferred over coarse global author metadata.

## Performance architecture

- Provider HTTP calls run **outside** SQLite write transactions.
- **Caching and rate limiting** reduce duplicate external requests.
- **Paginated provider retrieval** for interactive Analyze Authors pages.
- **Background jobs** for expensive Collaboration Insights calculations on large selections.
- SQLite uses **WAL mode and busy timeout** for safer concurrent access.
- The first Analyze Authors page can render from the first provider page **without** a full corpus crawl.

## Requirements

- Git
- [Node.js](https://nodejs.org/) (includes npm)
- [Python 3](https://www.python.org/)

Local data is stored in **SQLite**. No separate database server is required.

## Developer Setup

1. Clone the repository:

   ```bash
   git clone <repository-url>
   cd research-intelligence-tool
   ```

2. Create and configure the backend environment file:

   ```bash
   cp backend/.env.example backend/.env
   ```

   Edit `backend/.env`. At minimum, set `OPENALEX_API_KEY` for live researcher search. See [Optional environment variables](#optional-environment-variables) below.

3. Install dependencies, create the Python environment, initialize SQLite, and apply migrations:

   ```bash
   npm run setup
   ```

4. Start the frontend and backend together:

   ```bash
   npm run dev
   ```

   Press `Ctrl+C` to stop both. Vite prints the frontend URL when it starts (typically [http://localhost:5173/](http://localhost:5173/)).

### Optional environment variables

Configured in `backend/.env` (see `backend/.env.example`):

| Variable | Purpose |
| --- | --- |
| `OPENALEX_API_KEY` | **Recommended.** Live OpenAlex author/publication search |
| `ORCID_CLIENT_ID` / `ORCID_CLIENT_SECRET` | Optional OAuth credentials (public ORCID reads use `ORCID_ENABLED` without OAuth) |
| `ORCID_ENABLED` | Enable ORCID author search (default `true`) |
| `ARXIV_ENABLED` | Enable arXiv search (default `true`) |
| `ELSEVIER_API_KEY` | Scopus Serial Title API for journal metrics |
| `ELSEVIER_INST_TOKEN` | Optional institutional token for off-campus Elsevier access |
| `DATABASE_URL` | SQLite connection URL (default `sqlite+aiosqlite:///./author_identity.db`) |
| `AUTHOR_RESOLUTION_ENABLED` | Canonical author resolution during search (default `true`) |

Never commit real credentials. `backend/.env` is gitignored.

## Open the application

- App: [http://localhost:5173/](http://localhost:5173/) (or the URL printed by Vite)
- API docs: [http://localhost:8000/docs](http://localhost:8000/docs)

## Basic use

1. Choose **Authors** or **Grants** from the menu.
2. For authors, **All sources** is selected by default (or choose OpenAlex or ORCID).
3. Enter a search — author name, ORCID iD, or grant number.
4. Select authors or a grant.
5. Open publication results or **Analyze authors**.
6. Use filters, sorting, Insights, and exclusions as needed.
7. Download CSV when you need a full export.

## Testing

From the repository root (after `npm run setup`):

**Backend tests**

```bash
node scripts/backend-python.mjs -m pytest -q
```

Or from `backend/` with the virtualenv activated:

```bash
cd backend && python -m pytest -q
```

**Frontend tests**

```bash
npm --prefix frontend test
```

**Frontend production build**

```bash
npm --prefix frontend run build
```

**Setup script tests** (optional)

```bash
npm run test:setup
```

## Project structure

| Path | Description |
| --- | --- |
| `frontend/` | React app (Vite, MUI) |
| `backend/` | FastAPI API, SQLite database, Alembic migrations |
| `backend/app/api/` | HTTP routes (search, authors, analysis, grants, …) |
| `backend/app/integrations/openalex/` | OpenAlex client and search helpers |
| `backend/app/integrations/orcid/` | ORCID client, normalization, search |
| `backend/app/integrations/arxiv/` | arXiv Atom API client and parser |
| `backend/app/integrations/elsevier/` | Elsevier / Scopus journal-metrics client |
| `backend/app/services/author_resolution/` | Canonical author identity resolution |
| `backend/app/services/analysis/` | Publications analysis, Insights, CSV export |
| `backend/app/services/search/` | Unified multi-provider search orchestration |
| `backend/tests/` | Backend pytest suite |
| `backend/alembic/` | Database migrations |
| `scripts/` | Setup helpers used by `npm run setup` |

## Troubleshooting

- **Database / migrations** — rerun `npm run setup` or `npm run setup:database`. The SQLite file is `backend/author_identity.db`.
- **Missing API results** — set `OPENALEX_API_KEY` in `backend/.env` and restart `npm run dev`.
- **Permission denied creating the database** — make sure you can write to the `backend/` folder.
- **Port already in use** — stop other apps using ports `5173` (frontend) or `8000` (backend), then run `npm run dev` again.
- **OpenAlex, ORCID, or arXiv unavailable** — try again later, or switch source if one provider is down.
- **Empty results** — coverage differs by source; a query may return nothing even when the search is valid.
- **Journal metrics missing in Insights** — configure `ELSEVIER_API_KEY` (and `ELSEVIER_INST_TOKEN` if required for your access).

## Current limitations

- Until OpenAlex coverage is verified complete for the selection, Analyze Authors timeline/facets may still reflect the currently loaded sample rather than the full corpus (CSV export can still gather the full filtered set).
- Collaboration Insights depends on publication data already stored/synced for the selected authors; it does not live-crawl providers when you change filters.
- ORCID-only authors without a linked publication provider (for example, no OpenAlex match) may not yet have publication coverage.
- Scopus publication enrichment requires a DOI match and `ELSEVIER_API_KEY`; it never creates new canonical publication rows.
- Scopus **cited-by** / **Research Reach** functionality is **not yet implemented** in the product UI.

## Usage examples

### Example 1: Finding a publication shared by four authors

Publication: Chen, Chi-Fang, Jorge Garza-Vargas, Joel A. Tropp, and Ramon Van Handel, “A New Approach to Strong Convergence,” *Annals of Mathematics* 203, 555–602 (2026).

1. Open the application at [http://localhost:5173/](http://localhost:5173/).
2. Click **Authors** in the left menu.
3. Leave **All sources** selected (or choose **OpenAlex**).
4. Search for each author in turn:
   - Chi-Fang Chen
   - Jorge Garza-Vargas
   - Joel A. Tropp
   - Ramon Van Handel
5. From the search results, select the matching author profiles so they appear under **Selected authors**.
6. Click **Analyze authors**.
7. On the results page:
   - With **one** author checked, you see that author’s publications (**Publications by …**).
   - With **two or more** authors checked, you see only publications that include every checked author (**Common Publications**).
8. Keep all four author checkboxes selected and look in the table for **A New Approach to Strong Convergence**.
9. On this page you will see:
   - checkboxes for the selected authors at the top
   - filters (**Show filters** / **Hide filters**)
   - the **Publications over time** chart (based on loaded publications — see the on-page note)
   - the detailed publications table with clear pagination (range + page controls)
10. In the table, useful columns include:
    - **Authors** (the complete author list)
    - **Date**
    - **Journal / Venue**
    - **Citations**
    - **Grants** (when available)
    - **Source**
11. Hover an author name in the table to see available author and institution information.
12. Uncheck some author boxes to compare smaller groups. The chart and table update for the authors that remain checked.
13. Click **Analysis** to open **Collaboration Insights** — shared-publication counts, yearly collaboration, participation breakdowns, institution network/partnerships, citation activity, and Top Journals (with Scopus metrics when configured).
14. Click **Download CSV** to export **all** filtered publications, not only the rows currently visible on screen.

Note: the exact paper may not appear if OpenAlex has incomplete or delayed indexing for that work.

### Example 2: Exploring a large multi-author publication

Publication: Oh, Hyunseok, Viraj Dharod, Carl Padgett, Lillian B. Hughes Wyatt, Jayameenakshi Venkatraman, Shreyas Parthasarathy, Ekaterina Osipova, Ian Hedgepeth, Jeffrey V. Cady, Luca Basso, Yongqiang Wang, Michael Titze, Edward S. Bielejec, Andrew M. Mounce, Dirk Bouwmeester, and Ania C. Bleszynski Jayich, “Spin-Embedded Diamond Optomechanical Resonator With a Mechanical Quality Factor Exceeding One Million,” *Optica* 13, no. 3, 485–490 (2026).

1. Click **Authors** in the left menu and leave **All sources** selected (or choose **OpenAlex**).
2. Search for several authors from the publication and add matching profiles to **Selected authors**.
3. Select two or more matching profiles.
4. Click **Analyze authors**.
5. The default result is an intersection: only publications that contain **every** checked author are shown (**Common Publications**).
6. Use the author checkboxes to switch among:
   - all selected authors
   - pairs
   - smaller groups
   - one author only
7. The **Publications over time** chart and the publications table update for the active author combination (chart/facets reflect loaded publications only).
8. To filter results:
   - click **Show filters**
   - set **From year** / **To year**, and choose **Source**, **Journal / Venue**, **Grant**, or **Institution** as needed
   - checkbox selections update draft filters only
   - click **Apply filters** once to refresh the chart and table
9. Hover an author name in the table for available author and institution details.
10. A publication may list more than one grant number; available grants appear in the **Grants** column.
11. Click **Analysis** for Collaboration Insights on the current author selection and stored publication set.
12. Click **Download CSV** to export the full filtered publication list.

Note: selecting more authors usually returns fewer common publications, because every checked author must appear in the same publication.

Results always depend on source coverage. A paper or author may be missing, incomplete, or delayed in OpenAlex, ORCID, or arXiv even when the search is correct.
