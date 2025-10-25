#!/bin/sh
# make python3 callable as python
ln -sf /usr/bin/python3 /usr/local/bin/python
# now let Vercel do its normal Python build
vercel build