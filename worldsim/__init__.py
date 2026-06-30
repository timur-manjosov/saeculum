"""worldsim — History Machine: eine emergente Welt-Simulation.

Headless-Kern. Schichten / Einbahn-Abhaengigkeiten:

    config, rng  ->  models  ->  events  ->  systems  ->  driver
                                                              |
                                       chronicle  ->  (presentation)  ->  main

Der oeffentliche Einstiegspunkt ist :func:`worldsim.driver.simulate`.
"""

from worldsim.driver import simulate

__all__ = ["simulate"]
