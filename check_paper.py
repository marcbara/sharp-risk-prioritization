"""Static sanity checks for SHARP_paper_DSA26.tex.

Verifies:
  - All \\cite{...} keys have a matching \\bibitem{...}
  - All \\ref{...} keys have a matching \\label{...}
  - Reports orphan bibitems and unused labels (informational)
  - Rough page count estimate
"""
import re

text = open("SHARP_paper_DSA26.tex", encoding="utf-8").read()

cites = set()
for m in re.finditer(r"\\cite\{([^}]+)\}", text):
    for c in m.group(1).split(","):
        cites.add(c.strip())

bibitems = set(re.findall(r"\\bibitem\{([^}]+)\}", text))

print("Citations used in body:")
for c in sorted(cites):
    print(f"  {c}")
print()
print("Bibitems defined:")
for b in sorted(bibitems):
    print(f"  {b}")
print()

missing = cites - bibitems
orphans = bibitems - cites
print(f"UNDEFINED cites (in body but no bibitem): {sorted(missing) if missing else 'none'}")
print(f"ORPHAN bibitems (defined but never cited): {sorted(orphans) if orphans else 'none'}")
print()

labels = set(re.findall(r"\\label\{([^}]+)\}", text))
refs = set(re.findall(r"\\ref\{([^}]+)\}", text))
print(f"Labels defined: {sorted(labels)}")
print(f"Refs used: {sorted(refs)}")
print(f"UNDEFINED refs: {sorted(refs - labels) if refs - labels else 'none'}")
print(f"UNUSED labels: {sorted(labels - refs) if labels - refs else 'none'}")
print()
print(f"Total characters: {len(text)}")
print(f"Rough page estimate (~3000 chars/page LNCS): {len(text) / 3000:.1f}")
