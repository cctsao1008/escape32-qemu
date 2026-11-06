#!/usr/bin/env python3
"""Optional QEMU 6.2 debug-transport patch; never changes Guest peripherals."""
import argparse
from pathlib import Path
import subprocess

PIN='44f28df24767cf9dca1ddc9b23157737c4cbb645'
OLD='chr = qemu_chr_new("qtest", qtest_chrdev, NULL);'
NEW='chr = qemu_chr_new_noreplay("qtest", qtest_chrdev, false, NULL);'


def patch(text):
    if text.count(NEW)==1 and OLD not in text:return text
    if text.count(OLD)!=1 or NEW in text:raise ValueError('Pinned QTest transport anchor changed')
    return text.replace(OLD,NEW,1)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True)
    a=p.parse_args()
    actual=subprocess.check_output(['git','-C',str(a.source),'rev-parse','HEAD'],text=True).strip()
    if actual!=PIN:raise SystemExit('Refuse non-pinned QEMU source')
    path=a.source/'softmmu/qtest.c';before=path.read_text();after=patch(before)
    if after!=before:path.write_text(after)
    print('PASS_QTEST_NOREPLAY_DEBUG_TRANSPORT_ONLY')


if __name__=='__main__':main()
