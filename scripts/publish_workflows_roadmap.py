#!/usr/bin/env python3
"""Publish shipped workflow features once, preserving existing roadmap edits."""
import argparse
import sqlite3

ENTRIES = [
    ('Inventory and BOM imports', 'Import inventory from CSV with a downloadable template and a review step. Import project quantities by internal part number; update listed parts or replace the parts list.'),
    ('Bulk inventory and quick stock changes', 'Select components to move, tag, or adjust stock together. Preview every change before applying; changed records and insufficient stock block the batch.'),
    ('Project shopping lists and duplication', 'Plan purchases for multiple builds, group shortages by supplier, and export exact and whole-pack costs to CSV. Duplicate an existing project without changing stock.'),
    ('Camera and photo scanning', 'Read QR codes and barcodes with a camera or saved photo, then search inventory. Processing runs locally in the browser; manual and USB-scanner input remain available.'),
    ('Getting started and help center', 'A workspace checklist tracks storage, components, label downloads and projects. A help center covers imports, stock changes, shopping lists, scanning and labels.'),
    ('Inventory, storage and label usability improvements', 'Browse nested storage with counts, find low-stock parts, return to filtered search results, use a shorter component form, and design labels in inches or millimeters. Projects now show readiness and record builds with Undo.')
]
KEY='roadmap-published-workflows-v1'

def publish(db):
    db.execute('BEGIN IMMEDIATE')
    if db.execute('SELECT 1 FROM site_settings WHERE key=?',(KEY,)).fetchone():
        db.rollback()
        return 0
    count=0
    for position,(title,description) in enumerate(ENTRIES):
        if not db.execute('SELECT 1 FROM roadmap WHERE title=?',(title,)).fetchone():
            db.execute("INSERT INTO roadmap(title,description,status,position,published) VALUES(?,?,'Released',?,1)",(title,description,position))
            count+=1
    db.execute('INSERT INTO site_settings(key,value) VALUES(?,?)',(KEY,'1'))
    db.commit()
    return count

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',default='/var/lib/partshelf/inventory.db')
    args=parser.parse_args()
    with sqlite3.connect(args.database) as db:
        print('Published released roadmap entries:',publish(db))
