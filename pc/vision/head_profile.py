"""Head size used to estimate where the scalp is: average female, average male, or the user's own measurement.

Source for the averages: ANSUR II, the 2012 Anthropometric Survey of U.S. Army Personnel
(Gordon et al., 2015, NATICK/TR-15/007), 1,986 women and 4,082 men, measured by trained measurers.
Values are the 50th percentiles (medians), in mm, as listed in the ANSUR II data explorer:
https://ergoassessment.cam/ansur-2-data-explorer/   (data: https://www.openlab.psu.edu/datasets/ansur2/)

How a profile becomes the 3D head model (an ellipsoid centered at ear height):
  front/back half-size = head length / 2
  side half-size       = head breadth / 2
  top half-size        = ear (tragion) to top of head
A personalized profile scales the average of the two by the user's head circumference.
"""
import re
from dataclasses import dataclass

SOURCE = "ANSUR II (2012 U.S. Army anthropometric survey), medians"

#                 head length  head breadth  ear to top  circumference   (mm)
ANSUR_II = {
    "female": dict(length=190.0, breadth=147.0, ear_to_top=127.0, circumference=560.0),
    "male": dict(length=200.0, breadth=154.0, ear_to_top=131.0, circumference=574.0),
}
REFERENCE_LENGTH = 200.0   # the face model in head_scalp.py is drawn for a 200 mm long head

UNIT_MM = {"mm": 1.0, "millimeter": 1.0, "millimeters": 1.0, "millimetre": 1.0, "millimetres": 1.0,
           "cm": 10.0, "centimeter": 10.0, "centimeters": 10.0, "centimetre": 10.0, "centimetres": 10.0,
           "m": 1000.0, "meter": 1000.0, "meters": 1000.0, "metre": 1000.0, "metres": 1000.0,
           "in": 25.4, "inch": 25.4, "inches": 25.4, '"': 25.4, "''": 25.4,
           "ft": 304.8, "foot": 304.8, "feet": 304.8, "'": 304.8}

CIRC_MIN_MM, CIRC_MAX_MM = 450.0, 700.0   # adult head circumferences fall well inside this


@dataclass
class HeadProfile:
    label: str
    length: float
    breadth: float
    ear_to_top: float
    circumference: float

    @property
    def axes(self):
        """Ellipsoid half-sizes (front/back, side, top) in mm."""
        return (self.length / 2, self.breadth / 2, self.ear_to_top)

    @property
    def face_scale(self):
        """How much bigger/smaller than the reference face model."""
        return self.length / REFERENCE_LENGTH

    def describe(self):
        return (f"{self.label}: circumference {self.circumference / 10:.1f} cm, length {self.length / 10:.1f} cm, "
                f"width {self.breadth / 10:.1f} cm")


def average_profile(sex):
    d = ANSUR_II[sex]
    return HeadProfile(f"Average {sex}", **d)


def personalized_profile(circumference_mm):
    """Scale the average of the female and male heads so its circumference matches the user's."""
    avg = {k: (ANSUR_II["female"][k] + ANSUR_II["male"][k]) / 2 for k in ANSUR_II["male"]}
    s = circumference_mm / avg["circumference"]
    return HeadProfile("Personal", length=avg["length"] * s, breadth=avg["breadth"] * s,
                       ear_to_top=avg["ear_to_top"] * s, circumference=circumference_mm)


def parse_length(text):
    """'57 cm', '22.5in', '22.5 inches', '570 mm', '0.57 m', '22.5"'  ->  millimeters.
    Raises ValueError with a message a user can act on."""
    t = text.strip().lower().replace(",", ".")
    m = re.fullmatch(r"([0-9]*\.?[0-9]+)\s*([a-z\"']*)\.?", t)
    if not m:
        raise ValueError("Type a number followed by its unit, for example 57 cm or 22.5 in.")
    value, unit = float(m.group(1)), m.group(2)
    if not unit:
        raise ValueError("Add the unit after the number, for example 57 cm or 22.5 in.")
    if unit not in UNIT_MM:
        raise ValueError(f"Unknown unit '{unit}'. Use cm, mm, in, or m.")
    return value * UNIT_MM[unit]


def check_circumference(mm):
    if not CIRC_MIN_MM <= mm <= CIRC_MAX_MM:
        raise ValueError(f"{mm / 10:.1f} cm is outside the normal adult range "
                         f"({CIRC_MIN_MM / 10:.0f}-{CIRC_MAX_MM / 10:.0f} cm). Check the number and unit.")
    return mm


def ask_head_profile(input_fn=input, print_fn=print):
    """Terminal menu at startup."""
    print_fn("\nHairBarbot head size")
    print_fn("Select biological sex for the average head size, or enter your own measurement:")
    print_fn("  1. Female   (average head, ANSUR II)")
    print_fn("  2. Male     (average head, ANSUR II)")
    print_fn("  3. Personalized measurement (head circumference)")
    while True:
        choice = input_fn("Choose 1, 2 or 3: ").strip()
        if choice == "1":
            return average_profile("female")
        if choice == "2":
            return average_profile("male")
        if choice == "3":
            print_fn("Measure around the widest part of the head: just above the eyebrows and ears, "
                     "around the back. Type the number and unit, e.g. 57 cm or 22.5 in.")
            while True:
                try:
                    mm = check_circumference(parse_length(input_fn("Head circumference: ")))
                    return personalized_profile(mm)
                except ValueError as e:
                    print_fn(f"  {e}")
        print_fn("  Please type 1, 2 or 3.")
