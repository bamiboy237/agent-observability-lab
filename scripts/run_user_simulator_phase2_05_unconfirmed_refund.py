#!/usr/bin/env python3
"""Runnable live user simulator for phase2-05-unconfirmed-refund."""

import sys

from app.domain.user_simulator.simulator import main

if __name__ == "__main__":
    sys.argv[1:1] = ["phase2-05-unconfirmed-refund"]
    main()
