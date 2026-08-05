# Research Intelligence Platform

Search researchers, publications, and grants, then filter results, explore collaboration patterns, and export data to CSV.

Current data sources: **OpenAlex** and **arXiv**. Some arXiv author and grant matching is experimental.

## What it does

- Search authors
- Search works / publications
- Search publications by grant number
- Select one or more authors
- View one author’s publications
- Find publications shared by multiple authors
- Filter by year, source, journal/venue, grant, and author where supported
- View publication and collaboration analysis
- Export results to CSV

## Requirements

- Git
- [Node.js](https://nodejs.org/) (includes npm)
- [Python 3](https://www.python.org/)

Local data is stored in **SQLite**. No separate database server is required.

## Download and run

```bash
git clone <repository-url>
cd research-intelligence-tool
npm run setup
npm run dev
```

`npm run setup` installs dependencies, creates the Python environment, initializes the SQLite database, and applies migrations.

`npm run dev` starts the frontend and backend together in one terminal. Press `Ctrl+C` to stop both.

## Open the application

- App: [http://localhost:5173/](http://localhost:5173/)
- API docs: [http://localhost:8000/docs](http://localhost:8000/docs)

## Basic use

1. Choose **Authors**, **Grants**, or **Works / Publications** from the menu.
2. Choose a source (OpenAlex or arXiv).
3. Enter a search.
4. Select authors or a grant.
5. Open publication results.
6. Use filters and analysis tools.
7. Download CSV when you need a copy of the results.

## Project folders

| Folder | Description |
| --- | --- |
| `frontend/` | React app (Vite) |
| `backend/` | FastAPI API, SQLite database, and migrations |
| `scripts/` | Setup helpers used by `npm run setup` |

## Troubleshooting

- **Database / migrations** — rerun `npm run setup:database`. The SQLite file is `backend/author_identity.db`.
- **Permission denied creating the database** — make sure you can write to the `backend/` folder.
- **Port already in use** — stop other apps using ports `5173` (frontend) or `8000` (backend), then run `npm run dev` again.
- **OpenAlex or arXiv unavailable** — try again later, or switch source if one provider is down.
- **Empty results** — coverage differs by source; a query may return nothing even when the search is valid.

## Current limitations

- Provider metadata can be incomplete.
- arXiv author matching is not a verified identity.
- arXiv grant matching is based on metadata text matching.
- Institutions, ORCIDs, grants, or citation values may be unavailable.
- The author insights page currently uses demonstration data.

## Usage examples

### Example 1: Finding a publication shared by four authors

Publication: Chen, Chi-Fang, Jorge Garza-Vargas, Joel A. Tropp, and Ramon Van Handel, “A New Approach to Strong Convergence,” *Annals of Mathematics* 203, 555–602 (2026).

1. Open the application at [http://localhost:5173/](http://localhost:5173/).
2. Click **Authors** in the left menu.
3. Next to **Source:**, select **OpenAlex**.
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
   - the **Publications over time** chart
   - the detailed publications table
10. In the table, useful columns include:
    - **Authors** (the complete author list)
    - **Date**
    - **Journal / Venue**
    - **Citations**
    - **Grants** (when available)
    - **Source**
11. Hover an author name in the table to see available author and institution information.
12. Uncheck some author boxes to compare smaller groups. The chart and table update for the authors that remain checked.
13. Click **Analysis** to open **Author Collaboration Analysis**. That page shows shared-publication counts, yearly collaboration (**Collaborative publications by year**), multi-author and multi-institution breakdowns, **Institution partnerships**, **Citation activity of selected publications**, and **Top journals / venues**. This page currently uses demonstration data (look for the **Demo data** badge and notice).
14. Click **Download CSV** to export **all** filtered publications, not only the rows currently visible on screen. The button note says it exports all filtered publications with available author, institution, grant, venue, and source metadata.

Note: the exact paper may not appear if OpenAlex has incomplete or delayed indexing for that work.

### Example 2: Exploring a large multi-author publication

Publication: Oh, Hyunseok, Viraj Dharod, Carl Padgett, Lillian B. Hughes Wyatt, Jayameenakshi Venkatraman, Shreyas Parthasarathy, Ekaterina Osipova, Ian Hedgepeth, Jeffrey V. Cady, Luca Basso, Yongqiang Wang, Michael Titze, Edward S. Bielejec, Andrew M. Mounce, Dirk Bouwmeester, and Ania C. Bleszynski Jayich, “Spin-Embedded Diamond Optomechanical Resonator With a Mechanical Quality Factor Exceeding One Million,” *Optica* 13, no. 3, 485–490 (2026).

1. Click **Authors** in the left menu and select **OpenAlex** as the source.
2. Search for several authors from the publication and add matching profiles to **Selected authors**.
3. Select two or more matching profiles.
4. Click **Analyze authors**.
5. The default result is an intersection: only publications that contain **every** checked author are shown (**Common Publications**).
6. Use the author checkboxes to switch among:
   - all selected authors
   - pairs
   - smaller groups
   - one author only
7. The **Publications over time** chart and the publications table update for the active author combination.
8. To filter results:
   - click **Show filters**
   - set **From year** / **To year**, and choose **Source**, **Journal / Venue**, or **Grant** as needed
   - checkbox selections update draft filters only
   - click **Apply filters** once to refresh the chart and table
9. Hover an author name in the table for available author and institution details.
10. A publication may list more than one grant number; available grants appear in the **Grants** column.
11. Click **Analysis** to open **Author Collaboration Analysis**, where you can explore shared publications for pairs or groups, multi-author papers, multi-institution papers, institution partnerships, yearly collaboration, citation activity, and top journals. This page currently uses demonstration data.
12. Click **Download CSV** to export the full filtered publication list.

Note: selecting more authors usually returns fewer common publications, because every checked author must appear in the same publication.

Results always depend on source coverage. A paper or author may be missing, incomplete, or delayed in OpenAlex or arXiv even when the search is correct.
