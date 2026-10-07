"""Synthetic post-incident call surge. Each block exercises a scenario from the design list."""
import math
import random

random.seed(7)
ORIGIN = (40.7128, -74.0060)
_calls = []
_n = 0


def jitter(lat, lon, m):
    dy, dx = random.gauss(0, m), random.gauss(0, m)
    return lat + dy / 111000, lon + dx / (111000 * math.cos(math.radians(lat)))


def add(t, caller, text, at, acc=25, audio=None, jit=40, phone_at=None):
    global _n
    _n += 1
    lat, lon = jitter(*(phone_at or at), jit)
    _calls.append({"id": f"C{_n:03d}", "t": t, "caller": caller, "transcript": text, "audio": audio,
                   "lat": lat, "lon": lon, "accuracy_m": acc})


WAREHOUSE = (40.7128, -74.0060)
LINCOLN = (40.7326, -73.9815)
HWY = (40.7200, -74.0390)
RIVERSIDE = (40.6903, -73.9942)
MILL = (40.6858, -74.0280)

# 1. Warehouse fire: many different callers, different wording, repeat callers, weak GPS, third-party reporter
fire = ["There is a huge fire at the warehouse on 5th and Oak, lots of black smoke",
        "Building on fire near 5th and Oak, flames coming out of the roof",
        "I can see smoke and flames from the old warehouse, fire trucks needed",
        "Warehouse blaze on Oak, thick smoke everywhere",
        "Smoke is pouring out of the warehouse, it is burning badly",
        "Fire at the warehouse on 5th, you can see it from the highway"]
for i, t in enumerate([0, 1, 2, 3, 4, 6]):
    add(t, f"555-01{i:02d}", fire[i], WAREHOUSE, acc=random.choice([15, 30, 50]))
add(5, "555-0110", "Warehouse fire, workers are trapped on the second floor", WAREHOUSE)   # escalates cluster
add(8, "555-0101", "Calling again about the warehouse fire, it is spreading to the next building", WAREHOUSE)
add(11, "555-0102", "Third time calling, a person is trapped at a second floor window at 5th and Oak", WAREHOUSE)
add(9, "555-0111", "My apartment next to the warehouse is filling with smoke, my mother is elderly and cannot walk",
    WAREHOUSE, jit=60)
add(10, "555-0120", "Fire somewhere downtown, huge smoke near the old warehouse", WAREHOUSE, acc=1500, jit=300)  # cell-tower
add(13, "555-0121", "I am calling for my brother, he is stuck at 5th and Oak, the warehouse is on fire and he cannot get out",
    WAREHOUSE, phone_at=(40.78, -73.95), acc=20)                                                   # phone far away
add(16, "555-0122", "Fire at the warehouse, more smoke now, explosion sound a minute ago", WAREHOUSE)
add(22, "555-0123", "Warehouse fire still burning, flames spreading", WAREHOUSE)

# 2. Different emergency ~60 m from the fire: must NOT merge
add(18, "555-0130", "My father has chest pain and feels dizzy, we live on Oak next to the warehouse",
    (40.7132, -74.0053), acc=20)

# 3. Highway crash with a child
hwy = ["Multi car crash on the Highway 9 overpass, several vehicles",
       "Big collision at highway 9 overpass, cars everywhere",
       "Wreck on highway 9, a truck hit two cars",
       "Accident on the overpass, one car rolled over, a man is bleeding",
       "There are a lot of cars crashed on highway 9 overpass, a child is crying in a car"]
for i, t in enumerate([6, 7, 8, 9, 12]):
    add(t, f"555-02{i:02d}", hwy[i], HWY)
add(10, "555-0210", "Highway 9 overpass crash, driver is unconscious and not breathing", HWY)
add(14, "555-0211", "Cars on the overpass, traffic stopped, lots of people standing around", HWY)
add(30, "555-0212", "Small fender bender on Elm Street, no injuries, just exchanging info", (40.7000, -74.0200))

# 4. Lincoln High: starts as a fight (low), escalates when gunfire is reported; whisper call; negation
add(5, "555-0300", "A fight broke out near Lincoln High, I do not think anyone has a weapon", LINCOLN)
add(7, "555-0301", "Students fighting outside Lincoln High, a lot of shouting", LINCOLN)
add(12, "555-0302", "Shots fired near Lincoln High School, people are running", LINCOLN, audio="gunfire_bg")
add(13, "555-0303", "I heard gunshots at Lincoln High, kids are inside the building", LINCOLN)
add(14, "555-0304", "Lincoln High, gunfire, someone said there is a shooter", LINCOLN)
add(15, "555-0305", "...", LINCOLN, audio="whisper", jit=20)
add(17, "555-0306", "Please send police to Lincoln High, there is a man with a gun in the hallway", LINCOLN)

# 5. Cardiac arrest: reported by spouse and neighbor (third party), single real incident
add(20, "555-0400", "My husband is not breathing, he collapsed in the kitchen, Riverside Apartments", RIVERSIDE, acc=20)
add(22, "555-0401", "A man collapsed in the hallway at Riverside Apartments, he is not responding", RIVERSIDE, jit=25)

# 6. Flood / car in water, child in car
add(40, "555-0500", "Car stuck in the water at Mill Creek Bridge, the driver cannot get out, a child is in the back", MILL)
add(42, "555-0501", "Flooded road at Mill Creek Bridge, a car is submerged", MILL)
add(44, "555-0502", "Someone drowning at the Mill Creek Bridge, water is rising fast", MILL)

# 7. Noise: must not inflate counts or trigger priority
add(15, "555-0600", "Sorry, my phone was in my pocket, dialed by accident", (40.75, -73.95))
add(25, "555-0601", "My neighbors are watching a movie with explosions and gunshots way too loud", (40.74, -74.02))
add(33, "555-0602", "Neighbor's barbecue is making smoke, probably fine", (40.70, -74.03))
add(35, "555-0603", "", (40.69, -74.00), audio="silent", acc=80)         # open line, cannot assume it's a butt dial

# 8. Late wave: callers reporting the fire after TV coverage
for i, t in enumerate([50, 52, 55, 58, 63]):
    add(t, f"555-07{i:02d}", random.choice(fire), WAREHOUSE, acc=random.choice([20, 40]))

CALLS = _calls
