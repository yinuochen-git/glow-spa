#!/bin/bash
cd "$(dirname "$0")"
python3 serve.py
echo
read -n 1 -s -r -p "Press any key to close."
