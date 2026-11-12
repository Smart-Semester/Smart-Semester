# example transcript: ((# )+<actual transcript data>)
# Fall 2023
# Course	Title	Grade	Credits
# ENG 1310	COLLEGE WRITING I	B	3
	# 
# 
# Satisfied by: ENGL1301 - COMP & RHETORIC I - Lone Star College System
# 
# Spring 2024
# Course	Title	Grade	Credits
# ENG 1320	COLLEGE WRITING II	B	3
	# 
# 
# Satisfied by: ENGL1302 - COMP & RHETORIC II - Lone Star College System
# 
# Fall 2024
# Course	Title	Grade	Credits
# ENG 2310	BRIT LIT - 1785	A	3
	# 
# 
# Satisfied by: ENGL2322 - SURV BRIT LIT I-ANGLO SAX THRU - Lone Star College System
# MATH 2471	CALCULUS I	B	4
	# 
# 
# Satisfied by: MATH2413 - CALCULUS I - Lone Star College System
# POSI 2320	FUNCT AMER GOVT	A	3
	# 
# 
# Satisfied by: GOVT2305 - FEDERAL GOVT - Lone Star College System
# 
# Spring 2025
# Course	Title	Grade	Credits
# ENG 2320	BRIT LIT 1785 +	A	3
	# 
# 
# Satisfied by: ENGL2323 - SURV BRIT LIT II-RMNTIC THR PR - Lone Star College System
# MATH 2472	CALCULUS II	B	4
# 
# 
# Satisfied by: MATH2414 - CALCULUS II - Lone Star College System
# 
# Fall 2025
# Course	Title	Grade	Credits
# COMM 1310	FUND OF HUMAN COMMUNICATION	A	3
# CS 1428	FOUNDATIONS OF COMPUTER SCI I	A	4
# ECO 2315	PRIN MACROECON	CR	3
# GEO 1309	INTRO CULTURAL GEO	CR	3
# HIST 1310	HIST US TO 1877	CR	3
# HIST 1320	HIST US TO DATE	CR	3
# HIST 2310	W CIVIL TO 1715	CR	3
# HIST 2311	HIST WORLD CIV TO	CR	3
# HIST 2312	HS WORLD CIV FROM	CR	3
# MATH 2358	DISCRETE MATHEMATICS I	A	3
# POSI 2310	PRIN OF AM GOV	A	3
# 
# Spring 2026
# Course	Title	Grade	Credits
# ART 2313	INTRODUCTION TO FINE ARTS	A	3
# CHEM 1141	GEN CHEM LAB I	A	1
# CHEM 1341	GENERAL CHEMISTRY I	A	3
# CS 2308	FOUNDATNS OF CS II	A	3
# MATH 3398	DISCRETE MATHEMATICS II	A	3
# PHYS 2125	MECHANICS LAB	A	1
# PHYS 2325	MECHANICS	A	3
# 
# Fall 2026
# Course	Title	Grade	Credits
# CHEM 1142	GENERAL CHEMISTRY LAB II	IP	1
# CHEM 1342	GENERAL CHEM II	IP	3
# CS 2325	COMPUTER ORGANIZATION	IP	3
# CS 3358	DATA STRUCTURES AND ALGORITHMS	IP	3
# ENG 3303	TECHNICAL WRITING	IP	3
# PHIL 1305	PHIL & CRIT THNKNG	IP	3
# 
# Spring 2027
# Course	Title	Grade	Credits
# CS 2315	COMPUTER ETHICS	IP	3
# CS 3354	OBJECT-ORIENTED DESIGN & PROG	IP	3
# CS 3360	COMPUTING SYSTEMS FUNDAMENTALS	IP	3
# CS 4318	COMPILER CONSTRUCTION	IP	3

# could probably just use some REGEX
# ^(?P<code>[A-Z]{2,4})\s?(?P<number>\d{4})\s+(?P<title>.+?)\s+(?P<grade>[A-Z]{1,2})\s+(?P<credits>\d+(?:\.\d+)?)\s*$

def parse_transcript(transcript: str):
    # nothing so far
