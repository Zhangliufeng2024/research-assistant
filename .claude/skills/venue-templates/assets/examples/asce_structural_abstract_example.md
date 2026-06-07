# ASCE Abstract Example — Structural Engineering

**Journal**: Journal of Structural Engineering (ASCE)
**Paper type**: Numerical / experimental study
**Topic**: Seismic performance of steel moment frames with buckling-restrained braces

---

## Example Abstract

Buckling-restrained braces (BRBs) have been widely adopted to enhance the seismic
performance of steel moment-resisting frames (SMRFs), yet their interaction effects
under near-fault ground motions with velocity pulses remain poorly understood.
This study investigates the seismic response of BRB-SMRFs subjected to 40
pulse-type near-fault ground motion records selected from the PEER NGA-West2 database.
A three-dimensional finite element model of a nine-story prototype BRB-SMRF was
developed in OpenSees v3.5 and validated against published experimental data
(prediction error ≤4.3% for peak story drift).
Nonlinear response history analyses were performed for pulse periods ranging from
0.5 s to 4.0 s.
Results indicate that pulse-period-to-fundamental-period ratios in the range 0.5–1.0
amplify peak story drift demands by 38–62% relative to ordinary ground motions at
the same intensity level.
Maximum interstory drift ratios (IDRs) exceeded the ASCE 41-17 life-safety (LS)
limit of 2.5% in 35% of records when the pulse period matched the structural period.
BRB axial deformation ductility demands reached 14.2 under the most severe pulse
records, 1.8 times the AISC 341-22 design capacity.
These findings highlight the need for pulse-period-specific seismic demand factors
in the design of BRB-SMRFs located within 20 km of active fault traces.

---

## Annotation (Writing Guidance)

| Sentence | Function |
|----------|----------|
| "Buckling-restrained braces (BRBs)…yet their interaction effects…remain poorly understood." | Motivation and research gap in one sentence |
| "This study investigates…40 pulse-type near-fault ground motion records…" | Objective and scope — quantified |
| "A three-dimensional FE model…validated…(prediction error ≤4.3%)" | Method with validation evidence |
| "Results indicate that…amplify peak story drift demands by 38–62%" | Main finding — specific numbers |
| "Maximum IDRs exceeded the ASCE 41-17 LS limit of 2.5% in 35% of records" | Code-based performance context |
| "BRB axial deformation ductility demands reached 14.2…1.8 times AISC 341-22 capacity" | Second key finding — design relevance |
| "These findings highlight the need for pulse-period-specific…" | Practical significance / conclusion |

**ASCE Abstract Checklist:**
- [ ] Problem statement in ≤2 sentences
- [ ] Specific numerical objective (e.g., "40 records", "9-story prototype")
- [ ] Method described in 1–2 sentences including software/database
- [ ] Validation evidence with quantified error
- [ ] ≥2 quantitative key results
- [ ] Design code referenced (ASCE 41, AISC 341, ACI 318, etc.)
- [ ] Practical conclusion or implication
- [ ] ≤250 words
- [ ] No references, abbreviations at first use, or math symbols without definition

---

## Example Keywords

seismic performance; buckling-restrained braces; near-fault ground motions; velocity pulse; nonlinear response history analysis; interstory drift ratio

---

## Example Introduction Opening (First Two Paragraphs)

Steel moment-resisting frames (SMRFs) equipped with buckling-restrained braces
(BRBs) represent a class of dual lateral-force-resisting systems that combine the
ductility of moment connections with the energy dissipation capacity of yielding
metallic braces (Sabelli et al. 2003; Mahin et al. 2004).
Following widespread damage to conventional concentrically braced frames in the
1994 Northridge and 1995 Kobe earthquakes (Tremblay et al. 1996), BRBs were
developed to provide stable, symmetric hysteretic behavior under both tension and
compression, with core ductility capacities typically exceeding 20 (Iwata and Murai 2006).
Provisions governing the design of BRB-SMRFs are now codified in AISC 341-22
(AISC 2022) and ASCE 7-22 (ASCE 2022), and the system is employed in high-seismic
regions worldwide (Fahnestock et al. 2007).

Despite this widespread adoption, the response of BRB-SMRFs to near-fault ground
motions containing coherent velocity pulses remains an active area of research.
Near-fault records exhibit directivity effects that concentrate energy at the pulse
period ($T_p$), potentially creating resonance conditions when $T_p$ approaches the
structural fundamental period (Somerville et al. 1997; Bray and Rodriguez-Marek 2004).
Several studies have documented pulse-induced amplification of drift demands in
conventional SMRFs (Alavi and Krawinkler 2004; Luco and Cornell 2007), but the
combined effect of BRB yielding behavior and pulse-period resonance has not been
systematically characterized using modern ground motion databases and three-dimensional
structural models.
This study addresses this gap by \ldots
