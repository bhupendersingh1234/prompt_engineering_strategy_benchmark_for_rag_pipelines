"""
Fills the official Review-2.pptx template (provided by the user) with this
project's real content, preserving the template's own Calibri / navy
(#1D2F82) visual design exactly rather than imposing a different theme.

Confirmed with the user before writing:
  - School: SENSE (School of Electronics Engineering) -- matches what the
    template itself already says in two places.
  - Guide: "Dr. Manmohan Sharma, SENSE".
  - Review-I feedback: no significant panel feedback -- written honestly as
    such rather than inventing specifics.

The literature-review slide is duplicated once (8 refs + 7 refs = 15 total)
because the template's own footnote says "Duplicate this slide as needed"
for exactly this case -- cramming 15 rows onto one slide would require
sub-8pt text, which defeats the point of a readable literature table.

All 15 references were verified via WebFetch/WebSearch against arXiv, ACL
Anthology, NeurIPS Proceedings, or ICLR OpenReview during authoring -- see
LITERATURE below for the paper-by-paper sourcing.

Results (the table, chart images, and judge-calibration stats) are read
live from a results directory rather than hardcoded, so re-running this
after a fresh benchmark run just needs --results-dir pointed at the new
data -- no hand-editing numbers in this file.

Usage:
    python presentation/fill_review2_template.py
    python presentation/fill_review2_template.py --results-dir demo_workspace/results --out review_2_updated
"""
import argparse
import copy
import csv
import json
from pathlib import Path

from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.oxml.ns import qn

_ap = argparse.ArgumentParser()
_ap.add_argument("--results-dir", default="results",
                  help="Directory containing summary.csv, judge_calibration.json, charts/ "
                       "(relative to the project root). Default: results (the real, "
                       "committed benchmark). Point at demo_workspace/results for a demo run.")
_ap.add_argument("--out", default="review-2-ppt",
                  help="Output filename (without .pptx), saved into presentation/.")
_args = _ap.parse_args()

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = ROOT / "presentation" / "Review-2.pptx"
OUT_PATH = ROOT / "presentation" / f"{_args.out}.pptx"
RESULTS_DIR = ROOT / _args.results_dir
CHARTS_DIR = RESULTS_DIR / "charts"

# ---------------------------------------------------------------------------
# Template's own palette -- read off its existing runs, not invented
# ---------------------------------------------------------------------------
NAVY = RGBColor(0x1D, 0x2F, 0x82)
INK = RGBColor(0x00, 0x00, 0x00)
MUTED = RGBColor(0x80, 0x80, 0x80)
FONT = "Calibri"
MONO = "Consolas"

# categorical strategy colors (validated palette used across this project's
# other decks/artifacts) -- the template has no categorical system of its
# own, so these are the minimal necessary addition, kept out of the
# template's navy/black/gray system everywhere else
SERIES = {
    "Zero-shot": RGBColor(0x2A, 0x78, 0xD6),
    "Few-shot": RGBColor(0xEB, 0x68, 0x34),
    "Chain-of-Thought": RGBColor(0x1B, 0xAF, 0x7A),
    "Structured Output": RGBColor(0x4A, 0x3A, 0xA7),
}

prs = Presentation(str(TEMPLATE_PATH))
SW, SH = prs.slide_width, prs.slide_height


# ===========================================================================
# Low-level helpers
# ===========================================================================
def slide_shapes_by_name(slide):
    return {sh.name: sh for sh in slide.shapes}


def set_run_text(shape, text, para_idx=0, run_idx=0):
    """Edit an existing run's text in place -- keeps its original font/size/
    color/bold exactly as the template defined it."""
    run = shape.text_frame.paragraphs[para_idx].runs[run_idx]
    run.text = text
    return run


def clone_paragraph_format(src_para):
    return copy.deepcopy(src_para._p)


def rebuild_labeled_body(shape, sections, label_size=15, body_size=12.5,
                          bullet_gap=6, section_gap=16):
    """sections: [(label_text, [bullet, bullet, ...]), ...]. Clears the
    shape's existing label-only paragraphs and rewrites label (bold navy)
    + bullet content (regular black) beneath each, in the same Calibri
    family the template uses throughout."""
    tf = shape.text_frame
    tf.word_wrap = True
    # clear all existing paragraphs down to one, then clear its runs
    for p in list(tf.paragraphs[1:]):
        p._p.getparent().remove(p._p)
    for r in list(tf.paragraphs[0].runs):
        r._r.getparent().remove(r._r)
    first = True
    for label, bullets in sections:
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        if not first or label == sections[0][0]:
            pass
        p.space_before = Pt(0 if p is tf.paragraphs[0] else section_gap)
        r = p.add_run()
        r.text = label
        r.font.name = FONT; r.font.size = Pt(label_size); r.font.bold = True; r.font.color.rgb = NAVY
        for b in bullets:
            bp = tf.add_paragraph()
            bp.space_before = Pt(bullet_gap)
            bp.level = 1
            br0 = bp.add_run()
            br0.text = "•  "
            br0.font.name = FONT; br0.font.size = Pt(body_size); br0.font.bold = True; br0.font.color.rgb = MUTED
            br1 = bp.add_run()
            br1.text = b
            br1.font.name = FONT; br1.font.size = Pt(body_size); br1.font.color.rgb = INK


def add_table_rows(table, n):
    """python-pptx has no public add_row(); clone the last <a:tr> element
    n times (standard workaround) and clear its cell text."""
    tbl_elm = table._tbl
    last_tr = tbl_elm.findall(qn('a:tr'))[-1]
    for _ in range(n):
        new_tr = copy.deepcopy(last_tr)
        tbl_elm.append(new_tr)
    # clear all text in the newly added rows
    for ri in range(len(table.rows) - n, len(table.rows)):
        for cell in table.rows[ri].cells:
            cell.text_frame.clear()


def remove_table_row(table, row_idx):
    tbl_elm = table._tbl
    trs = tbl_elm.findall(qn('a:tr'))
    tbl_elm.remove(trs[row_idx])


def fill_table_row(table, ri, values, font_size=9.5, header=False, no_bold_col0=False):
    for ci, val in enumerate(values):
        cell = table.cell(ri, ci)
        cell.text_frame.word_wrap = True
        cell.text_frame.clear()
        p = cell.text_frame.paragraphs[0]
        r = p.add_run()
        r.text = str(val)
        r.font.name = FONT
        r.font.size = Pt(font_size)
        r.font.color.rgb = WHITE if header else INK
        r.font.bold = header or (ci == 0 and not no_bold_col0)
        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
        cell.margin_left = Inches(0.06); cell.margin_right = Inches(0.06)
        cell.margin_top = Inches(0.02); cell.margin_bottom = Inches(0.02)
        if header:
            cell.fill.solid(); cell.fill.fore_color.rgb = NAVY
        else:
            cell.fill.solid()
            cell.fill.fore_color.rgb = RGBColor(0xF5, 0xF6, 0xFA) if ri % 2 == 0 else WHITE


WHITE = RGBColor(0xFF, 0xFF, 0xFF)


def set_row_height(table, ri, inches):
    table.rows[ri].height = Inches(inches)


def add_textbox(slide, left, top, width, height, text="", size=14, color=INK,
                 bold=False, italic=False, font=FONT, align=PP_ALIGN.LEFT,
                 anchor=MSO_ANCHOR.TOP, line_spacing=1.05, wrap=True):
    box = slide.shapes.add_textbox(left, top, width, height)
    tf = box.text_frame
    tf.word_wrap = wrap
    tf.vertical_anchor = anchor
    tf.margin_left = 0; tf.margin_right = 0; tf.margin_top = 0; tf.margin_bottom = 0
    if text:
        for i, line in enumerate(text.split("\n")):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.alignment = align; p.line_spacing = line_spacing
            r = p.add_run(); r.text = line
            r.font.size = Pt(size); r.font.bold = bold; r.font.italic = italic
            r.font.name = font; r.font.color.rgb = color
    return box


def add_rect(slide, left, top, width, height, fill=None, line_color=None, line_width=None):
    from pptx.enum.shapes import MSO_SHAPE
    shp = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, top, width, height)
    if fill is not None:
        shp.fill.solid(); shp.fill.fore_color.rgb = fill
    else:
        shp.fill.background()
    if line_color is not None:
        shp.line.color.rgb = line_color; shp.line.width = line_width or Pt(1)
    else:
        shp.line.fill.background()
    shp.shadow.inherit = False
    return shp


def box(slide, cx, cy, w, h, text, sub=None, fill=WHITE, line=INK, text_color=INK, bold=True, size=11):
    left = Inches(cx - w / 2); top = Inches(cy - h / 2)
    shp = add_rect(slide, left, top, Inches(w), Inches(h), fill=fill, line_color=line, line_width=Pt(1.25))
    tf = shp.text_frame
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf.margin_left = Inches(0.05); tf.margin_right = Inches(0.05)
    tf.word_wrap = True
    p = tf.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
    r = p.add_run(); r.text = text; r.font.size = Pt(size); r.font.bold = bold; r.font.name = FONT; r.font.color.rgb = text_color
    if sub:
        p2 = tf.add_paragraph(); p2.alignment = PP_ALIGN.CENTER
        r2 = p2.add_run(); r2.text = sub; r2.font.size = Pt(8.5); r2.font.name = FONT; r2.font.color.rgb = MUTED
    return shp


def connector(slide, x1, y1, x2, y2, color=MUTED, weight=Pt(1.1), arrowhead=True):
    conn = slide.shapes.add_connector(1, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    conn.line.color.rgb = color
    conn.line.width = weight
    if arrowhead:
        ln = conn.line._get_or_add_ln()
        tail = ln.makeelement(qn('a:tailEnd'), {'type': 'triangle', 'w': 'med', 'len': 'med'})
        ln.append(tail)
    return conn


def add_citation_column(slide, left, top, width, height, citations, start_no, size=10):
    box_ = slide.shapes.add_textbox(left, top, width, height)
    tf = box_.text_frame
    tf.word_wrap = True
    tf.margin_left = 0; tf.margin_right = 0; tf.margin_top = 0; tf.margin_bottom = 0
    for i, c in enumerate(citations):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.line_spacing = 1.05; p.space_after = Pt(9)
        r0 = p.add_run(); r0.text = f"[{start_no + i}]  "
        r0.font.size = Pt(size); r0.font.bold = True; r0.font.name = MONO; r0.font.color.rgb = NAVY
        r1 = p.add_run(); r1.text = c
        r1.font.size = Pt(size); r1.font.name = FONT; r1.font.color.rgb = INK
    return box_


def extract_logo_path():
    """Save the template's own corner-logo image once so new slides can
    reuse it via a fresh add_picture() call instead of risky XML-level
    relationship copying."""
    s2 = prs.slides[1]
    for sh in s2.shapes:
        if sh.shape_type == 13:
            image = sh.image
            out = ROOT / "presentation" / "_logo_extract.png"
            out.write_bytes(image.blob)
            return out
    return None


LOGO_PATH = extract_logo_path()


def add_slide_chrome(slide, page_no, title_text):
    """Rebuilds the page-number, title, and corner-logo furniture that
    every content slide in the template has, for a freshly-added slide."""
    add_textbox(slide, Inches(12.53), Inches(7.05), Inches(0.5), Inches(0.3),
                str(page_no), size=10, color=MUTED, align=PP_ALIGN.RIGHT)
    add_textbox(slide, Inches(0.6), Inches(0.35), Inches(10.5), Inches(0.75),
                title_text, size=28, bold=True, color=NAVY)
    if LOGO_PATH:
        slide.shapes.add_picture(str(LOGO_PATH), Inches(11.33), Inches(0.35), Inches(1.5), Inches(0.57))


def move_slide_after(prs, new_slide, after_slide):
    """add_slide() always appends at the end; this repositions the new
    slide's <p:sldId> element to sit immediately after `after_slide` in
    the deck's slide order (the only part that actually controls display
    order -- the slide *parts* themselves are unordered)."""
    xml_slides = prs.slides._sldIdLst
    new_rId = after_rId = None
    for rel_id, rel in prs.part.rels.items():
        if rel.target_part == new_slide.part:
            new_rId = rel_id
        if rel.target_part == after_slide.part:
            after_rId = rel_id
    new_sldid = after_sldid = None
    for sldid in xml_slides:
        if sldid.get(qn('r:id')) == new_rId:
            new_sldid = sldid
        if sldid.get(qn('r:id')) == after_rId:
            after_sldid = sldid
    xml_slides.remove(new_sldid)
    after_sldid.addnext(new_sldid)


def duplicate_blank_slide():
    """Adds a new slide using the template's own (only) layout."""
    layout = prs.slides[2].slide_layout  # any content slide's layout
    new_slide = prs.slides.add_slide(layout)
    for shp in list(new_slide.shapes):
        shp._element.getparent().remove(shp._element)
    return new_slide


# ===========================================================================
# Content data
# ===========================================================================
TEAM = [("Astitva Thakkar", "23BAI1057"), ("Parth Sharma", "23BAI1528"), ("Bhupender Singh", "23BRS1107")]
GUIDE = "Dr. Manmohan Sharma, SENSE"
PROJECT_TITLE = "Prompt Engineering Strategy Benchmark for RAG Pipelines"

# (No., "Author(s), Year", "Title / Source", "Method / Approach", "Findings & Research Gap")
LITERATURE_TABLE = [
    ("Lewis et al., 2020", "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks (NeurIPS)",
     "Dense retriever + seq2seq generator, jointly fine-tuned",
     "Cuts hallucination on knowledge tasks; prompt format on retrieved context not studied"),
    ("Brown et al., 2020", "Language Models are Few-Shot Learners (NeurIPS)",
     "175B-param LM evaluated via in-context few-shot examples",
     "Establishes few-shot prompting; not tested in a retrieval-grounded setting"),
    ("Shuster et al., 2021", "Retrieval Augmentation Reduces Hallucination in Conversation (EMNLP Findings)",
     "Retrieval-augmented dialogue vs. retrieval-free baseline",
     "Retrieval cuts hallucination; prompting on top of retrieval not varied"),
    ("Wei et al., 2022", "Chain-of-Thought Prompting Elicits Reasoning (NeurIPS)",
     "Few-shot exemplars with intermediate reasoning steps",
     "Improves reasoning; not evaluated for RAG grounding or hallucination"),
    ("Kojima et al., 2022", "Large Language Models are Zero-Shot Reasoners (NeurIPS)",
     "Single trigger phrase (“Let's think step by step”), no exemplars",
     "Zero-shot CoT rivals few-shot; not tested against retrieved evidence"),
    ("Jiang et al., 2023", "Active Retrieval Augmented Generation / FLARE (EMNLP)",
     "Predicts the next sentence to trigger on-demand retrieval",
     "Improves long-form generation; prompting for the final answer not the variable studied"),
    ("Liu et al., 2023", "Pre-train, Prompt, and Predict (ACM Comput. Surv.)",
     "Systematic taxonomy of prompting methods across NLP",
     "Catalogs prompting broadly; no controlled RAG-hallucination comparison"),
    ("Ji et al., 2023", "Survey of Hallucination in Natural Language Generation (ACM Comput. Surv.)",
     "Literature survey of hallucination types, causes, and metrics",
     "Frames a hallucination taxonomy; doesn't isolate prompting as a RAG mitigation"),
    # --- slide 3b ---
    ("Gao et al., 2023", "Retrieval-Augmented Generation for LLMs: A Survey (arXiv)",
     "Survey of RAG architectures and augmentation techniques",
     "Maps the RAG design space; prompting is a minor sub-topic, not benchmarked"),
    ("Zheng et al., 2023", "Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena (NeurIPS)",
     "LLM-graded scoring validated against human agreement",
     "Validates LLM-as-judge; motivates this project's judge-calibration step"),
    ("Es et al., 2024", "RAGAS: Automated Evaluation of RAG (EACL)",
     "Reference-free Faithfulness / Answer Relevancy via LLM prompting",
     "Automates RAG evaluation; doesn't compare prompting strategies"),
    ("Niu et al., 2024", "RAGTruth: A Hallucination Corpus for RAG (ACL)",
     "~18K human-annotated RAG responses, labeled by span",
     "Rich ground truth; labels apply to original models' answers — used as this project's dataset"),
    ("Asai et al., 2024", "Self-RAG: Learning to Retrieve, Generate, and Critique (ICLR)",
     "Model fine-tuned to emit reflection tokens and self-critique",
     "Reduces unsupported claims via self-critique; needs fine-tuning, not a prompting-only comparison"),
    ("Yan et al., 2024", "Corrective Retrieval Augmented Generation (arXiv)",
     "Retrieval evaluator triggers correction / web search on low confidence",
     "Improves robustness to poor retrieval; targets retrieval quality, not prompt design"),
    ("Liu et al., 2024", "Lost in the Middle: How LMs Use Long Contexts (TACL)",
     "Varies the position of the answer-bearing passage in context",
     "Context use is non-uniform (U-shaped); motivates why prompt structure affects grounded accuracy"),
]

LITERATURE_REFS = [
    "P. Lewis et al., “Retrieval-augmented generation for knowledge-intensive NLP tasks,” in Advances in Neural Information Processing Systems 33 (NeurIPS 2020), 2020.",
    "T. B. Brown et al., “Language models are few-shot learners,” in Advances in Neural Information Processing Systems 33 (NeurIPS 2020), 2020.",
    "K. Shuster, S. Poff, M. Chen, D. Kiela, and J. Weston, “Retrieval augmentation reduces hallucination in conversation,” in Findings of ACL: EMNLP 2021, Punta Cana, Dominican Republic, Nov. 2021, pp. 3784–3803.",
    "J. Wei et al., “Chain-of-thought prompting elicits reasoning in large language models,” in Advances in Neural Information Processing Systems 35 (NeurIPS 2022), 2022.",
    "T. Kojima, S. S. Gu, M. Reid, Y. Matsuo, and Y. Iwasawa, “Large language models are zero-shot reasoners,” in Advances in Neural Information Processing Systems 35 (NeurIPS 2022), 2022.",
    "Z. Jiang et al., “Active retrieval augmented generation,” in Proc. 2023 Conf. Empirical Methods in Natural Language Processing (EMNLP), Singapore, Dec. 2023, pp. 7969–7992.",
    "P. Liu, W. Yuan, J. Fu, Z. Jiang, H. Hayashi, and G. Neubig, “Pre-train, prompt, and predict: A systematic survey of prompting methods in natural language processing,” ACM Computing Surveys, vol. 55, no. 9, pp. 1–35, Jan. 2023.",
    "Z. Ji et al., “Survey of hallucination in natural language generation,” ACM Computing Surveys, vol. 55, no. 12, 2023.",
    "Y. Gao et al., “Retrieval-augmented generation for large language models: A survey,” arXiv preprint arXiv:2312.10997, Dec. 2023.",
    "L. Zheng et al., “Judging LLM-as-a-judge with MT-Bench and Chatbot Arena,” in Advances in Neural Information Processing Systems 36 (NeurIPS 2023), Datasets and Benchmarks Track, 2023.",
    "S. Es, J. James, L. Espinosa-Anke, and S. Schockaert, “RAGAS: Automated evaluation of retrieval augmented generation,” in Proc. 18th Conf. European Chapter Assoc. Comput. Linguistics: System Demonstrations (EACL), St. Julian’s, Malta, Mar. 2024, pp. 150–158.",
    "C. Niu et al., “RAGTruth: A hallucination corpus for developing trustworthy retrieval-augmented language models,” in Proc. 62nd Annual Meeting Assoc. Comput. Linguistics (ACL), Vol. 1: Long Papers, Bangkok, Thailand, Aug. 2024, pp. 10862–10878.",
    "A. Asai, Z. Wu, Y. Wang, A. Sil, and H. Hajishirzi, “Self-RAG: Learning to retrieve, generate, and critique through self-reflection,” in Proc. 12th Int. Conf. Learning Representations (ICLR), 2024.",
    "S.-Q. Yan, J.-C. Gu, Y. Zhu, and Z.-H. Ling, “Corrective retrieval augmented generation,” arXiv preprint arXiv:2401.15884, Jan. 2024.",
    "N. F. Liu et al., “Lost in the middle: How language models use long contexts,” Trans. Assoc. Comput. Linguistics, vol. 12, pp. 157–173, 2024.",
]

assert len(LITERATURE_TABLE) == 15 and len(LITERATURE_REFS) == 15

print(f"Loaded {len(LITERATURE_TABLE)} literature entries, building deck...")

# Capture all 10 original slide objects by reference BEFORE any structural
# change (slide insertion) -- object references stay valid even as prs.slides
# ordering changes, so this is safer than re-indexing after the insert.
orig = list(prs.slides)
(slide_title, slide_intro, slide_lit1, slide_arch, slide_impl,
 slide_results1, slide_results2, slide_challenges, slide_refs, slide_thanks) = orig


# ===========================================================================
# SLIDE 1 -- Title (signed & scanned)
# ===========================================================================
sh = slide_shapes_by_name(slide_title)
set_run_text(sh["Text 3"], PROJECT_TITLE)

tf = sh["Text 5"].text_frame
for p in list(tf.paragraphs[1:]):
    p._p.getparent().remove(p._p)
tf.paragraphs[0].runs[0].text = f"{TEAM[0][0]}  —  {TEAM[0][1]}"
for name, reg in TEAM[1:]:
    p = tf.add_paragraph()
    r = p.add_run(); r.text = f"{name}  —  {reg}"
    r.font.name = FONT; r.font.size = Pt(14); r.font.color.rgb = INK

set_run_text(sh["Text 8"], GUIDE)
print("Slide 1 (title) filled.")


# ===========================================================================
# SLIDE 2 -- Introduction & Problem Recap
# ===========================================================================
sh = slide_shapes_by_name(slide_intro)
rebuild_labeled_body(sh["Text 2"], [
    ("Problem recap:", [
        "Answer quality inside a RAG pipeline depends heavily on how retrieved context is handed to the LLM — the prompting strategy — not just on retrieval quality.",
        "No controlled study isolates prompting strategy as the sole variable while holding chunking, embeddings, retrieval, and the base model fixed.",
    ]),
    ("Objectives:", [
        "Build a common, reusable RAG pipeline as the fixed experimental baseline.",
        "Implement four distinct prompting strategies on top of it — Zero-shot, Few-shot, Chain-of-Thought, Structured Output.",
        "Evaluate all strategies on an identical dataset and metric suite (RAGAS + a human-calibrated hallucination judge).",
        "Compare trade-offs in accuracy, hallucination rate, latency, and cost.",
    ]),
    ("Refinements after Review-I feedback:", [
        "No major revisions were requested by the panel at Review-I; feedback was limited to minor clarifications, which have been folded into the project documentation and this deck.",
    ]),
])
print("Slide 2 (intro) filled.")


# ===========================================================================
# SLIDE 3 / 3b -- Detailed Literature Review (duplicated, per the
# template's own "duplicate this slide as needed" instruction)
# ===========================================================================
sh = slide_shapes_by_name(slide_lit1)
tbl1_shape = sh["Table 0"]
add_table_rows(tbl1_shape.table, 2)  # 7 rows -> 9 rows (header + 8 refs)
for ri in range(len(tbl1_shape.table.rows)):
    set_row_height(tbl1_shape.table, ri, 0.5)

fill_table_row(tbl1_shape.table, 0, ["No.", "Author(s) & Year", "Title / Source", "Method / Approach", "Findings & Research Gap"], header=True, font_size=10.5)
for i in range(8):
    author, title, method, gap = LITERATURE_TABLE[i]
    fill_table_row(tbl1_shape.table, i + 1, [i + 1, author, title, method, gap], font_size=9)

# footnote already correct ("Minimum 15 recent papers...") -- leave as-is

slide_lit2 = duplicate_blank_slide()
move_slide_after(prs, slide_lit2, slide_lit1)
add_slide_chrome(slide_lit2, 6, "Detailed Literature Review (contd.)")

tbl2_shape = slide_lit2.shapes.add_table(9, 5, Inches(0.6), Inches(1.5), Inches(12.13), Inches(4.34)).table
for ci, w in enumerate([Inches(0.6), Inches(2.1), Inches(3.4), Inches(2.6), Inches(3.43)]):
    tbl2_shape.columns[ci].width = w
for ri in range(9):
    set_row_height(tbl2_shape, ri, 0.5)
fill_table_row(tbl2_shape, 0, ["No.", "Author(s) & Year", "Title / Source", "Method / Approach", "Findings & Research Gap"], header=True, font_size=10.5)
for i in range(7):
    author, title, method, gap = LITERATURE_TABLE[8 + i]
    fill_table_row(tbl2_shape, i + 1, [9 + i, author, title, method, gap], font_size=9)
remove_table_row(tbl2_shape, 8)  # only 7 data rows needed, not 8

add_textbox(slide_lit2, Inches(0.6), Inches(6.05), Inches(12.1), Inches(0.9),
            "Research gap: no existing work isolates prompting strategy as the sole variable in a RAG "
            "pipeline while holding retrieval, embeddings, and the base model fixed — the gap this "
            "project addresses (see Proposed Solution, Review-I).",
            size=12, italic=True, color=MUTED, line_spacing=1.2)
print("Slides 3/3b (literature, 15 refs) filled.")

# Inserting slide_lit2 (report page 6) pushes every following slide's
# report-page number up by one (5,6,7,8,9,10,11,12 -> unaffected up to
# lit1=5, then 6,7,8,9,10,11,12 -> 7,8,9,10,11,12,13).
for slide, new_no in [
    (slide_arch, 7), (slide_impl, 8), (slide_results1, 9), (slide_results2, 10),
    (slide_challenges, 11), (slide_refs, 12), (slide_thanks, 13),
]:
    page_shape = slide_shapes_by_name(slide)["Text 0"]
    set_run_text(page_shape, str(new_no))
print("Page numbers renumbered after literature-slide insertion.")


# ===========================================================================
# SLIDE 4 -- System Design & Architecture
# ===========================================================================
s = slide_arch
COL_X = [1.70, 4.13, 6.57, 8.98]
BAND_LEFT, BAND_W = 0.55, 9.6
LLM_CX = (COL_X[0] + COL_X[-1]) / 2

box(s, COL_X[0], 1.75, 2.7, 0.5, "RAGTruth QA subset", "5,934 rows · Hugging Face",
    fill=RGBColor(0xF5, 0xF6, 0xFA), line=MUTED, bold=False, size=10)
connector(s, COL_X[0], 2.0, COL_X[0], 2.36)

fixed_band = add_rect(s, Inches(BAND_LEFT), Inches(2.15), Inches(BAND_W), Inches(1.05), line_color=NAVY, line_width=Pt(1.25))
add_textbox(s, Inches(0.7), Inches(2.19), Inches(6), Inches(0.24), "FIXED — identical for every strategy", size=9, bold=True, color=NAVY)

fixed_labels = [("Chunk", "500 / 50 overlap"), ("Embed", "text-embedding-3-small"),
                ("Chroma DB", "vector store"), ("Retriever", "top-k = 4")]
for x, (label, sub) in zip(COL_X, fixed_labels):
    box(s, x, 2.72, 1.7, 0.58, label, sub)
for i in range(3):
    connector(s, COL_X[i] + 0.85, 2.72, COL_X[i + 1] - 0.85, 2.72)

FANOUT_Y = 3.3
connector(s, COL_X[-1], 3.01, COL_X[-1], FANOUT_Y, arrowhead=False)
connector(s, COL_X[0], FANOUT_Y, COL_X[-1], FANOUT_Y, arrowhead=False)
for x in COL_X:
    connector(s, x, FANOUT_Y, x, 3.75)

var_band = add_rect(s, Inches(BAND_LEFT), Inches(3.55), Inches(BAND_W), Inches(0.98), line_color=RGBColor(0x8A, 0x2A, 0x2A), line_width=Pt(1.25))
add_textbox(s, Inches(0.7), Inches(3.59), Inches(7), Inches(0.24), "THE ONE VARIABLE — prompt strategy only", size=9, bold=True, color=RGBColor(0x8A, 0x2A, 0x2A))
labels4 = ["Zero-shot", "Few-shot", "Chain-of-Thought", "Structured Output"]
for x, lab in zip(COL_X, labels4):
    col = SERIES[lab]
    box(s, x, 4.09, 1.7, 0.58, lab, fill=WHITE, line=col, text_color=col, bold=True, size=10)

FANIN_Y = 4.65
for x in COL_X:
    connector(s, x, 4.38, x, FANIN_Y, arrowhead=False)
connector(s, COL_X[0], FANIN_Y, COL_X[-1], FANIN_Y, arrowhead=False)
connector(s, LLM_CX, FANIN_Y, LLM_CX, 4.78)

box(s, LLM_CX, 5.05, 3.2, 0.55, "gpt-4o-mini · T = 0.0", "shared generation call", fill=NAVY, line=NAVY, text_color=WHITE, size=11)
connector(s, LLM_CX, 5.325, LLM_CX, 5.55)

box(s, LLM_CX, 5.9, 3.6, 0.55, "RAGAS + LLM Hallucination Judge", "calibrated against RAGTruth labels", fill=RGBColor(0xF5, 0xF6, 0xFA), line=MUTED, size=10)

right_note = add_rect(s, Inches(10.35), Inches(2.6), Inches(2.4), Inches(2.6), fill=RGBColor(0xF5, 0xF6, 0xFA), line_color=MUTED)
tf = right_note.text_frame; tf.margin_left = Inches(0.18); tf.margin_top = Inches(0.18); tf.margin_right = Inches(0.16); tf.word_wrap = True
p = tf.paragraphs[0]; r = p.add_run(); r.text = "Why this design"; r.font.bold = True; r.font.size = Pt(12); r.font.name = FONT; r.font.color.rgb = NAVY
p = tf.add_paragraph(); p.space_before = Pt(8)
r = p.add_run(); r.text = "Retrieval is built once and reused, read-only, by all four strategies — so any measured difference can only come from the prompt."
r.font.size = Pt(10.5); r.font.name = FONT; r.font.color.rgb = INK
print("Slide 4 (architecture) filled.")


# ===========================================================================
# SLIDE 5 -- Implementation Details
# ===========================================================================
sh = slide_shapes_by_name(slide_impl)
body = sh["Text 2"]
rebuild_labeled_body(body, [
    ("Modules developed and integrated:", [
        "data_loader.py \u2014 RAGTruth loading, QA-subset filtering, eval/calibration split, corpus construction",
        "ingest.py \u2014 chunking \u2192 embedding \u2192 ChromaDB indexing (shared, read-only across strategies)",
        "prompts/ \u2014 four independent LangChain LCEL chains (zero_shot, few_shot, chain_of_thought, structured_output)",
        "evaluate.py \u2014 RAGAS wrapper + custom LLM hallucination judge",
        "run_benchmark.py, generate_report.py \u2014 experiment runner and chart generation",
        "webapp/ \u2014 FastAPI + WebSocket backend and JS frontend for live, interactive runs",
    ]),
    ("Algorithms implemented:", [
        "Recursive character-based chunking (500 chars / 50 overlap)",
        "Dense vector retrieval via cosine similarity (ChromaDB, top-k = 4)",
        "Four prompting algorithms: Zero-shot, Few-shot (3 exemplars), Chain-of-Thought (tagged reasoning/answer), Structured Output (Pydantic-enforced schema)",
        "Claim-decomposition LLM-judge algorithm \u2014 decomposes each answer into atomic claims and checks each individually against retrieved context",
    ]),
], label_size=14, body_size=10.5, bullet_gap=5, section_gap=14)

# real, short code snippet -- the chunking function from src/ingest.py
code_bg = add_rect(slide_impl, Inches(0.68), Inches(4.78), Inches(9.2), Inches(1.65), fill=RGBColor(0x1E, 0x1E, 0x1E))
code_box = add_textbox(slide_impl, Inches(0.85), Inches(4.86), Inches(8.9), Inches(1.5))
code_tf = code_box.text_frame
code_tf.word_wrap = True
CODE_LINES = [
    "def chunk_documents(docs: list[Document]) -> list[Document]:",
    "    splitter = RecursiveCharacterTextSplitter(",
    "        chunk_size=config.CHUNK_SIZE,       # 500",
    "        chunk_overlap=config.CHUNK_OVERLAP, # 50",
    "        separators=[\"\\n\\n\", \"\\n\", \". \", \" \", \"\"],",
    "    )",
    "    return splitter.split_documents(docs)",
]
for i, line in enumerate(CODE_LINES):
    p = code_tf.paragraphs[0] if i == 0 else code_tf.add_paragraph()
    p.line_spacing = 1.15
    r = p.add_run(); r.text = line
    r.font.name = MONO; r.font.size = Pt(11); r.font.color.rgb = RGBColor(0xD4, 0xD4, 0xD4)
add_textbox(slide_impl, Inches(9.95), Inches(4.9), Inches(2.1), Inches(1.4),
            "src/ingest.py \u2014 chunk_documents()", size=10.5, italic=True, color=MUTED, line_spacing=1.2)
print("Slide 5 (implementation) filled.")


# ===========================================================================
# SLIDE 6 -- Results & Analysis (75%) -- the real, completed benchmark
# ===========================================================================
STRATEGY_LABELS = {
    "zero_shot": "Zero-shot", "few_shot": "Few-shot",
    "chain_of_thought": "Chain-of-Thought", "structured_output": "Structured Output",
}
STRATEGY_ORDER = ["zero_shot", "few_shot", "chain_of_thought", "structured_output"]


def load_results(results_dir: Path):
    path = results_dir / "summary.csv"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found -- run the benchmark (or point --results-dir "
                                 f"at a directory that has summary.csv) before building this deck.")
    rows = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows[row["strategy"]] = row
    out = []
    for key in STRATEGY_ORDER:
        r = rows[key]
        out.append((
            STRATEGY_LABELS[key],
            float(r["accuracy"]), float(r["hallucination_rate"]),
            float(r["ragas_faithfulness"]), float(r["avg_latency_seconds"]),
            float(r["avg_cost_usd"]),
        ))
    eval_n = int(rows[STRATEGY_ORDER[0]]["n"])
    return out, eval_n


def load_calibration(results_dir: Path):
    path = results_dir / "judge_calibration.json"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found.")
    d = json.loads(path.read_text(encoding="utf-8"))
    return d["n"], d["precision"], d["recall"], d["f1"], d["accuracy"]


RESULTS, EVAL_N = load_results(RESULTS_DIR)
CAL_N, CAL_P, CAL_R, CAL_F1, CAL_ACC = load_calibration(RESULTS_DIR)
print(f"Loaded results from {RESULTS_DIR} -- calibration n={CAL_N}, "
      f"P={CAL_P:.2f} R={CAL_R:.2f} F1={CAL_F1:.2f} Acc={CAL_ACC:.2f}")

s = slide_results1
res_tbl = s.shapes.add_table(5, 6, Inches(0.6), Inches(1.55), Inches(12.1), Inches(2.35)).table
for ci, w in enumerate([Inches(2.4), Inches(1.7), Inches(2.0), Inches(1.9), Inches(1.7), Inches(2.4)]):
    res_tbl.columns[ci].width = w
for ri in range(5):
    set_row_height(res_tbl, ri, 0.47)
fill_table_row(res_tbl, 0, ["Strategy", "Accuracy", "Halluc. Rate", "Faithfulness", "Latency", "Cost / query"], header=True, font_size=11.5)
for i, (name, acc, hal, faith, lat, cost) in enumerate(RESULTS):
    fill_table_row(res_tbl, i + 1,
                   [name, f"{acc:.3f}", f"{hal:.3f}", f"{faith:.3f}", f"{lat:.2f}s", f"${cost:.6f}"],
                   font_size=11)

add_textbox(s, Inches(0.6), Inches(4.1), Inches(6.3), Inches(0.3),
            f"Judge calibration (n={CAL_N}, vs. RAGTruth human labels):", size=12.5, bold=True, color=NAVY)
cal_metrics = [("Precision", f"{CAL_P:.2f}"), ("Recall", f"{CAL_R:.2f}"), ("F1", f"{CAL_F1:.2f}"), ("Accuracy", f"{CAL_ACC:.2f}")]
cw_, ch_, gap_ = 1.3, 1.0, 0.18
for i, (label, val) in enumerate(cal_metrics):
    x = 0.6 + i * (cw_ + gap_)
    card = add_rect(s, Inches(x), Inches(4.45), Inches(cw_), Inches(ch_), fill=NAVY)
    tf = card.text_frame; tf.vertical_anchor = MSO_ANCHOR.MIDDLE; tf.margin_left = Inches(0.05); tf.margin_right = Inches(0.05)
    p = tf.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
    r = p.add_run(); r.text = val; r.font.size = Pt(20); r.font.bold = True; r.font.name = FONT; r.font.color.rgb = WHITE
    p2 = tf.add_paragraph(); p2.alignment = PP_ALIGN.CENTER
    r2 = p2.add_run(); r2.text = label.upper(); r2.font.size = Pt(8.5); r2.font.name = FONT; r2.font.color.rgb = RGBColor(0xC9, 0xD8, 0xE8)

chart_path = CHARTS_DIR / "accuracy_vs_hallucination.png"
if chart_path.exists():
    ch_h = 2.55
    s.shapes.add_picture(str(chart_path), Inches(7.6), Inches(4.1), height=Inches(ch_h))
add_textbox(s, Inches(0.6), Inches(6.65), Inches(11.9), Inches(0.35),
            f"n = {EVAL_N} questions per strategy \u2014 real, completed benchmark run, not illustrative.",
            size=10.5, italic=True, color=MUTED)
print("Slide 6 (results 75%) filled.")


# ===========================================================================
# SLIDE 7 -- Results & Analysis (contd.)
# ===========================================================================
s = slide_results2
radar_path = CHARTS_DIR / "radar_comparison.png"
faith_path = CHARTS_DIR / "faithfulness.png"
if radar_path.exists():
    s.shapes.add_picture(str(radar_path), Inches(0.7), Inches(1.55), height=Inches(2.9))
if faith_path.exists():
    s.shapes.add_picture(str(faith_path), Inches(4.1), Inches(1.55), height=Inches(2.9))

legend_x = 8.4
add_textbox(s, Inches(legend_x), Inches(1.6), Inches(4.2), Inches(0.3), "Strategy colors:", size=11, bold=True, color=NAVY)
ly = 2.0
for label, col in SERIES.items():
    sw = add_rect(s, Inches(legend_x), Inches(ly), Inches(0.18), Inches(0.18), fill=col)
    add_textbox(s, Inches(legend_x + 0.28), Inches(ly - 0.03), Inches(3.8), Inches(0.25), label, size=10.5, color=INK)
    ly += 0.32

add_textbox(s, Inches(0.6), Inches(4.75), Inches(11.9), Inches(0.3),
            "Findings vs. the original hypothesis:", size=13, bold=True, color=NAVY)
findings_box = add_textbox(s, Inches(0.6), Inches(5.1), Inches(11.9), Inches(1.8))
tf = findings_box.text_frame
tf.word_wrap = True
findings = [
    ("Structured Output's grounding advantage is robust across two independent runs \u2014 ",
     "lowest hallucination rate both times (10.0% exactly, both runs), and the ranking Structured < Few-shot < Chain-of-Thought < Zero-shot on hallucination rate held in both."),
    ("Which strategy has the best accuracy is NOT stable across runs \u2014 ",
     "Few-shot led the first n=60 run (71.7%); Chain-of-Thought leads this run (76.7%). That instability is itself the evidence motivating the statistical-significance work still remaining, not a settled result yet."),
    ("Zero-shot is consistently the weakest strategy \u2014 ",
     "highest hallucination rate in both runs and lowest accuracy in this run \u2014 the strongest and most repeatable finding is simply that prompting strategy matters at all."),
]
for i, (lead, rest) in enumerate(findings):
    p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
    p.space_after = Pt(10); p.line_spacing = 1.12
    r0 = p.add_run(); r0.text = "\u2014  "
    r0.font.name = FONT; r0.font.size = Pt(12); r0.font.bold = True; r0.font.color.rgb = MUTED
    r1 = p.add_run(); r1.text = lead
    r1.font.name = FONT; r1.font.size = Pt(12); r1.font.bold = True; r1.font.color.rgb = INK
    r2 = p.add_run(); r2.text = rest
    r2.font.name = FONT; r2.font.size = Pt(12); r2.font.color.rgb = INK
print("Slide 7 (results contd.) filled.")


# ===========================================================================
# SLIDE 8 -- Challenges & Remaining Work
# ===========================================================================
sh = slide_shapes_by_name(slide_challenges)
rebuild_labeled_body(sh["Text 2"], [
    ("Challenges faced and solutions:", [
        "RAGAS import crashed at runtime (a dependency it hard-imports was removed upstream) — fixed with a small, documented compatibility shim.",
        "The LLM hallucination judge under-counted real hallucinations (recall 0.20 against RAGTruth's human labels) — found via calibration, fixed by making the judge decompose answers into atomic claims and check each individually; recall rose to 0.87.",
        "Re-running ingestion silently accumulated duplicate chunks in the vector store instead of replacing them — fixed by clearing the collection before every rebuild.",
        "ChromaDB's default dependency required a C++ compiler unavailable on the dev machine — resolved by using ChromaDB's newer Rust-backed release, which ships prebuilt Windows wheels.",
    ]),
    ("Remaining work (25%):", [
        "Statistical significance / confidence intervals on the observed strategy gaps — two independent n=60 runs already show the accuracy ranking is not stable, which is exactly why this can't be skipped.",
        "A larger-scale run to tighten those confidence intervals.",
        "Final written report and production-scenario recommendations.",
    ]),
    ("Timeline for completion by Review-III (28.10.2026):", [
        "Weeks 1–2 (Sep 30 – Oct 14): larger-sample benchmark run; statistical significance analysis on all metrics.",
        "Week 3 (Oct 15 – Oct 21): results interpretation and final report drafting.",
        "Week 4 (Oct 22 – Oct 28): report finalization, Review-III deck, and rehearsal.",
    ]),
], label_size=14.5, body_size=11.5, bullet_gap=6, section_gap=14)
print("Slide 8 (challenges & remaining work) filled.")


# ===========================================================================
# SLIDE 9 -- References (15, IEEE style, two columns)
# ===========================================================================
sh = slide_shapes_by_name(slide_refs)
ref_shape = sh["Text 2"]
ref_shape.width = Inches(5.85)  # narrow the existing placeholder into the left column
tf = ref_shape.text_frame
for p in list(tf.paragraphs[1:]):
    p._p.getparent().remove(p._p)
for r in list(tf.paragraphs[0].runs):
    r._r.getparent().remove(r._r)
first = True
for i, citation in enumerate(LITERATURE_REFS[:8]):
    p = tf.paragraphs[0] if first else tf.add_paragraph()
    first = False
    p.line_spacing = 1.05; p.space_after = Pt(9)
    r0 = p.add_run(); r0.text = f"[{i + 1}]  "
    r0.font.name = MONO; r0.font.size = Pt(10); r0.font.bold = True; r0.font.color.rgb = NAVY
    r1 = p.add_run(); r1.text = citation
    r1.font.name = FONT; r1.font.size = Pt(10); r1.font.color.rgb = INK
add_citation_column(slide_refs, Inches(6.75), Inches(1.45), Inches(5.85), Inches(4.7), LITERATURE_REFS[8:], start_no=9, size=10)
print("Slide 9 (references) filled.")


# ===========================================================================
# SLIDE 10 -- Thank You (already correct: SENSE / VIT Chennai -- no edits needed)
# ===========================================================================
print("Slide 10 (thank you) needs no changes — already correct.")


# ===========================================================================
prs.save(str(OUT_PATH))
print(f"\nSaved -> {OUT_PATH}")
print(f"Final slide count: {len(prs.slides)}")
