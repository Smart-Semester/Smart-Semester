# Three groups of models live in schemas.py: 
#   A. Request:  planned codes (list of str) + completed courses
#                (each: code, grade). "completed" may be empty/missing,
#                which is the "no transcript" branch.
#   B. Catalog response: course code, title, prerequisites tree,
#                corequisites tree. The tree is a nested model
#                (all_of / any_of / course / manual nodes).
#   C. Result, one per planned course: status
#                (eligible / not_eligible / cannot_verify / unknown_course),
#                what was unmet, and anything needing a manual check.
