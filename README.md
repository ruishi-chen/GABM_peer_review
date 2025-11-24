## GABM peer review simulation

This repository explores **how generative agent-based models (GABM)** can be used to run **simulated experiments on peer-review organizational composition**—for example, what happens to accept/reject patterns when some fraction of reviewers are LLM-based agents instead of humans.

- **High-level idea**:  
  - Use real ICLR 2025 submissions and human reviews to estimate paper-level “quality”.  
  - Plug that into a simple agent-based simulation where reviewer agents (human-like vs. LLM-like) generate reviews and panel decisions.  
  - Vary the **mix of human vs. agent reviewers** to study how conference-level decisions and fairness metrics might shift.

## Files and workflow

- **`00_download_PDFs/00_Get_PDF_url.ipynb`**  
  - Uses the OpenReview API to fetch **all ICLR 2025 submissions**, explore their metadata (titles, abstracts, etc.), and build a CSV of paper IDs and PDF URLs (`2025_iclr_pdfs_urls.csv`).

- **`00_download_PDFs/01_get_and_parse_PDF.py`**  
  - Script to **download all ICLR 2025 PDFs** listed in `2025_iclr_pdfs_urls.csv` and parse them with a running **Grobid** server.  
  - For each paper it creates a folder under `ICLR2025_papers/` containing the raw PDF, the TEI XML from Grobid, and a small `meta.json` with IDs, title, and URL.  
  - Run from the repo root (with Grobid running, default `http://localhost:8070`):

```bash
conda activate llm-abm
python 00_download_PDFs/01_get_and_parse_PDF.py
```

- **`01_get_human_review.ipynb`**  
  - Pulls **human review data** for ICLR 2025 from OpenReview (ratings, review text, and decisions), aligned with the submissions.  
  - Extracts per-review fields (e.g., rating, summary, strengths/weaknesses, confidence) and the final decision for each paper, and saves a flat CSV (e.g., `ICLR2025_human_reviews.csv`) used by the simulation.

- **`02_setup_simulation.ipynb`**  
  - Sets up the **generative agent-based peer-review simulation**.  
  - Loads the human review CSV, parses numeric ratings, and aggregates to paper-level statistics (mean rating, decision, etc.) used as proxies for latent paper quality.  
  - Defines simple behavioral models for **human vs. agent reviewers** (different noise/bias parameters), a panel decision rule, and then runs experiments where you vary the **share of agent reviewers** and examine how accept/reject outcomes change across papers.

At a glance: start with `00_Get_PDF_url.ipynb` and `01_get_and_parse_PDF.py` if you need raw papers/metadata, use `01_get_human_review.ipynb` to construct the empirical review dataset, and then run `02_setup_simulation.ipynb` to explore GABM-based peer-review scenarios.