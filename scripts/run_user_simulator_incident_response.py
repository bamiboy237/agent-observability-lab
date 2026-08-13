#!/usr/bin/env python3
"""Runnable live user simulator for incident_response."""

import sys

from app.domain.user_simulator.simulator import main

if __name__ == "__main__":
    sys.argv[1:1] = ["reference-incident_response"]
    main()
