"""Write a tiny test paper (a one-page PDF) for the browser check. Usage: make_paper.py OUT.pdf"""
import sys

import pymupdf

doc = pymupdf.open()
page = doc.new_page()
y = 72


def line(text, size=11, gap=16):
    global y
    page.insert_text((72, y), text, fontsize=size)
    y += gap


line("Probing Syntax in Pretrained Encoders", 16, 26)
line("Abstract", 13, 20)
line("We study probing of syntax in pretrained encoders and report accuracy on three datasets.")
line("1 Introduction", 13, 24)
line("Our contributions are a new probing dataset and a layer-wise analysis.")
line("2 Method", 13, 24)
line("We train with weak supervision from automatically parsed sentences.")
line("3 Experiments", 13, 24)
line("Table 2 reports accuracy of 71.2 on SST-2 and 64.0 on CoLA.")
doc.save(sys.argv[1])
