"""Write a tiny test paper for the browser check. Usage: make_paper.py OUT.pdf [long]

Default: a one-page PDF. With "long": four pages, with the experiments (Table 2) on page 4, so that scrolling to a cited
passage is visible.
"""
import sys

import pymupdf

long = len(sys.argv) > 2 and sys.argv[2] == "long"
doc = pymupdf.open()
page = doc.new_page()
y = 72


def line(text, size=11, gap=16):
    global y
    page.insert_text((72, y), text, fontsize=size)
    y += gap


def next_page():
    global page, y
    page = doc.new_page()
    y = 72


FILLER = ["The encoders are frozen and a small classifier is trained on each layer in turn.",
          "Sentences come from a public corpus and are parsed automatically before training.",
          "Each probe sees one token representation and predicts its syntactic label.",
          "We repeat every run with three random seeds and average the scores."]

line("Probing Syntax in Pretrained Encoders", 16, 26)
line("Abstract", 13, 20)
line("We study probing of syntax in pretrained encoders and report accuracy on three datasets.")
line("1 Introduction", 13, 24)
line("Our contributions are a new probing dataset and a layer-wise analysis.")
line("2 Method", 13, 24)
line("We train with weak supervision from automatically parsed sentences.")
if long:
    for p in range(2):
        next_page()
        for i in range(30):
            line(FILLER[i % len(FILLER)] + (" " + "Details are given below." if i % 7 == 0 else ""))
    next_page()
line("3 Experiments", 13, 24)
line("Table 2 reports accuracy of 71.2 on SST-2 and 64.0 on CoLA.")
doc.save(sys.argv[1])
