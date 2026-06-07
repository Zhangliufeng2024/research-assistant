# Common Statistical Pitfalls

## P-Value Misinterpretations

### Pitfall 1: P-Value = Probability Hypothesis is True
**Misconception:** p = .05 means 5% chance the null hypothesis is true.

**Reality:** P-value is the probability of observing data this extreme (or more) *if* the null hypothesis is true. It says nothing about the probability the hypothesis is true.

**Correct interpretation:** "If there were truly no effect, we would observe data this extreme only 5% of the time."

### Pitfall 2: Non-Significant = No Effect
**Misconception:** p > .05 proves there's no effect.

**Reality:** Absence of evidence ≠ evidence of absence. Non-significant results may indicate:
- Insufficient statistical power
- True effect too small to detect
- High variability
- Small sample size

**Better approach:**
- Report confidence intervals
- Conduct power analysis
- Consider equivalence testing

### Pitfall 3: Significant = Important
**Misconception:** Statistical significance means practical importance.

**Reality:** With large samples, trivial effects become "significant." A statistically significant 0.1 IQ point difference is meaningless in practice.

**Better approach:**
- Report effect sizes
- Consider practical significance
- Use confidence intervals

### Pitfall 4: P = .049 vs. P = .051
**Misconception:** These are meaningfully different because one crosses the .05 threshold.

**Reality:** These represent nearly identical evidence. The .05 threshold is arbitrary.

**Better approach:**
- Treat p-values as continuous measures of evidence
- Report exact p-values
- Consider context and prior evidence

### Pitfall 5: One-Tailed Tests Without Justification
**Misconception:** One-tailed tests are free extra power.

**Reality:** One-tailed tests assume effects can only go one direction, which is rarely true. They're often used to artificially boost significance.

**When appropriate:** Only when effects in one direction are theoretically impossible or equivalent to null.

## Multiple Comparisons Problems

### Pitfall 6: Multiple Testing Without Correction
**Problem:** Testing 20 hypotheses at p < .05 gives ~65% chance of at least one false positive.

**Examples:**
- Testing many outcomes
- Testing many subgroups
- Conducting multiple interim analyses
- Testing at multiple time points

**Solutions:**
- Bonferroni correction (divide α by number of tests)
- False Discovery Rate (FDR) control
- Prespecify primary outcome
- Treat exploratory analyses as hypothesis-generating

### Pitfall 7: Subgroup Analysis Fishing
**Problem:** Testing many subgroups until finding significance.

**Why problematic:**
- Inflates false positive rate
- Often reported without disclosure
- "Interaction was significant in women" may be random

**Solutions:**
- Prespecify subgroups
- Use interaction tests, not separate tests
- Require replication
- Correct for multiple comparisons

### Pitfall 8: Outcome Switching
**Problem:** Analyzing many outcomes, reporting only significant ones.

**Detection signs:**
- Secondary outcomes emphasized
- Incomplete outcome reporting
- Discrepancy between registration and publication

**Solutions:**
- Preregister all outcomes
- Report all planned outcomes
- Distinguish primary from secondary

## Sample Size and Power Issues

### Pitfall 9: Underpowered Studies
**Problem:** Small samples have low probability of detecting true effects.

**Consequences:**
- High false negative rate
- Significant results more likely to be false positives
- Overestimated effect sizes (when significant)

**Solutions:**
- Conduct a priori power analysis
- Aim for 80-90% power
- Consider effect size from prior research

### Pitfall 10: Post-Hoc Power Analysis
**Problem:** Calculating power after seeing results is circular and uninformative.

**Why useless:**
- Non-significant results always have low "post-hoc power"
- It recapitulates the p-value without new information

**Better approach:**
- Calculate confidence intervals
- Plan replication with adequate sample
- Conduct prospective power analysis for future studies

### Pitfall 11: Small Sample Fallacy
**Problem:** Trusting results from very small samples.

**Issues:**
- High sampling variability
- Outliers have large influence
- Assumptions of tests violated
- Confidence intervals very wide

**Guidelines:**
- Be skeptical of n < 30
- Check assumptions carefully
- Consider non-parametric tests
- Replicate findings

## Effect Size Misunderstandings

### Pitfall 12: Ignoring Effect Size
**Problem:** Focusing only on significance, not magnitude.

**Why problematic:**
- Significance ≠ importance
- Can't compare across studies
- Doesn't inform practical decisions

**Solutions:**
- Always report effect sizes
- Use standardized measures (Cohen's d, r, η²)
- Interpret using field conventions
- Consider minimum clinically important difference

### Pitfall 13: Misinterpreting Standardized Effect Sizes
**Problem:** Treating Cohen's d = 0.5 as "medium" without context.

**Reality:**
- Field-specific norms vary
- Some fields have larger typical effects
- Real-world importance depends on context

**Better approach:**
- Compare to effects in same domain
- Consider practical implications
- Look at raw effect sizes too

### Pitfall 14: Confusing Explained Variance with Importance
**Problem:** "Only explains 5% of variance" = unimportant.

**Reality:**
- Height explains ~5% of variation in NBA player salary but is crucial
- Complex phenomena have many small contributors
- Predictive accuracy ≠ causal importance

**Consideration:** Context matters more than percentage alone.

## Correlation and Causation

### Pitfall 15: Correlation Implies Causation
**Problem:** Inferring causation from correlation.

**Alternative explanations:**
- Reverse causation (B causes A, not A causes B)
- Confounding (C causes both A and B)
- Coincidence
- Selection bias

**Criteria for causation:**
- Temporal precedence
- Covariation
- No plausible alternatives
- Ideally: experimental manipulation

### Pitfall 16: Ecological Fallacy
**Problem:** Inferring individual-level relationships from group-level data.

**Example:** Countries with more chocolate consumption have more Nobel laureates doesn't mean eating chocolate makes you win Nobels.

**Why problematic:** Group-level correlations may not hold at individual level.

### Pitfall 17: Simpson's Paradox
**Problem:** Trend appears in groups but reverses when combined (or vice versa).

**Example:** Treatment appears worse overall but better in every subgroup.

**Cause:** Confounding variable distributed differently across groups.

**Solution:** Consider confounders and look at appropriate level of analysis.

## Regression and Modeling Pitfalls

### Pitfall 18: Overfitting
**Problem:** Model fits sample data well but doesn't generalize.

**Causes:**
- Too many predictors relative to sample size
- Fitting noise rather than signal
- No cross-validation

**Solutions:**
- Use cross-validation
- Penalized regression (LASSO, ridge)
- Independent test set
- Simpler models

### Pitfall 19: Extrapolation Beyond Data Range
**Problem:** Predicting outside the range of observed data.

**Why dangerous:**
- Relationships may not hold outside observed range
- Increased uncertainty not reflected in predictions

**Solution:** Only interpolate; avoid extrapolation.

### Pitfall 20: Ignoring Model Assumptions
**Problem:** Using statistical tests without checking assumptions.

**Common violations:**
- Non-normality (for parametric tests)
- Heteroscedasticity (unequal variances)
- Non-independence
- Linearity
- No multicollinearity

**Solutions:**
- Check assumptions with diagnostics
- Use robust methods
- Transform data
- Use appropriate non-parametric alternatives

### Pitfall 21: Treating Non-Significant Covariates as Eliminating Confounding
**Problem:** "We controlled for X and it wasn't significant, so it's not a confounder."

**Reality:** Non-significant covariates can still be important confounders. Significance ≠ confounding.

**Solution:** Include theoretically important covariates regardless of significance.

### Pitfall 22: Collinearity Masking Effects
**Problem:** When predictors are highly correlated, true effects may appear non-significant.

**Manifestations:**
- Large standard errors
- Unstable coefficients
- Sign changes when adding/removing variables

**Detection:**
- Variance Inflation Factors (VIF)
- Correlation matrices

**Solutions:**
- Remove redundant predictors
- Combine correlated variables
- Use regularization methods

## Specific Test Misuses

### Pitfall 23: T-Test for Multiple Groups
**Problem:** Conducting multiple t-tests instead of ANOVA.

**Why wrong:** Inflates Type I error rate dramatically.

**Correct approach:**
- Use ANOVA first
- Follow with planned comparisons or post-hoc tests with correction

### Pitfall 24: Pearson Correlation for Non-Linear Relationships
**Problem:** Using Pearson's r for curved relationships.

**Why misleading:** r measures linear relationships only.

**Solutions:**
- Check scatterplots first
- Use Spearman's ρ for monotonic relationships
- Consider polynomial or non-linear models

### Pitfall 25: Chi-Square with Small Expected Frequencies
**Problem:** Chi-square test with expected cell counts < 5.

**Why wrong:** Violates test assumptions, p-values inaccurate.

**Solutions:**
- Fisher's exact test
- Combine categories
- Increase sample size

### Pitfall 26: Paired vs. Independent Tests
**Problem:** Using independent samples test for paired data (or vice versa).

**Why wrong:**
- Wastes power (paired data analyzed as independent)
- Violates independence assumption (independent data analyzed as paired)

**Solution:** Match test to design.

## Confidence Interval Misinterpretations

### Pitfall 27: 95% CI = 95% Probability True Value Inside
**Misconception:** "95% chance the true value is in this interval."

**Reality:** The true value either is or isn't in this specific interval. If we repeated the study many times, 95% of resulting intervals would contain the true value.

**Better interpretation:** "We're 95% confident this interval contains the true value."

### Pitfall 28: Overlapping CIs = No Difference
**Problem:** Assuming overlapping confidence intervals mean no significant difference.

**Reality:** Overlapping CIs are less stringent than difference tests. Two CIs can overlap while the difference between groups is significant.

**Guideline:** Overlap of point estimate with other CI is more relevant than overlap of intervals.

### Pitfall 29: Ignoring CI Width
**Problem:** Focusing only on whether CI includes zero, not precision.

**Why important:** Wide CIs indicate high uncertainty. "Significant" effects with huge CIs are less convincing.

**Consider:** Both significance and precision.

## Bayesian vs. Frequentist Confusions

### Pitfall 30: Mixing Bayesian and Frequentist Interpretations
**Problem:** Making Bayesian statements from frequentist analyses.

**Examples:**
- "Probability hypothesis is true" (Bayesian) from p-value (frequentist)
- "Evidence for null" from non-significant result (frequentist can't support null)

**Solution:**
- Be clear about framework
- Use Bayesian methods for Bayesian questions
- Use Bayes factors to compare hypotheses

### Pitfall 31: Ignoring Prior Probability
**Problem:** Treating all hypotheses as equally likely initially.

**Reality:** Extraordinary claims need extraordinary evidence. Prior plausibility matters.

**Consider:**
- Plausibility given existing knowledge
- Mechanism plausibility
- Base rates

## Data Transformation Issues

### Pitfall 32: Dichotomizing Continuous Variables
**Problem:** Splitting continuous variables at arbitrary cutoffs.

**Consequences:**
- Loss of information and power
- Arbitrary distinctions
- Discarding individual differences

**Exceptions:** Clinically meaningful cutoffs with strong justification.

**Better:** Keep continuous or use multiple categories.

### Pitfall 33: Trying Multiple Transformations
**Problem:** Testing many transformations until finding significance.

**Why problematic:** Inflates Type I error, is a form of p-hacking.

**Better approach:**
- Prespecify transformations
- Use theory-driven transformations
- Correct for multiple testing if exploring

## Missing Data Problems

### Pitfall 34: Listwise Deletion by Default
**Problem:** Automatically deleting all cases with any missing data.

**Consequences:**
- Reduced power
- Potential bias if data not missing completely at random (MCAR)

**Better approaches:**
- Multiple imputation
- Maximum likelihood methods
- Analyze missingness patterns

### Pitfall 35: Ignoring Missing Data Mechanisms
**Problem:** Not considering why data are missing.

**Types:**
- MCAR (Missing Completely at Random): Safe to delete
- MAR (Missing at Random): Can impute
- MNAR (Missing Not at Random): May bias results

**Solution:** Analyze patterns, use appropriate methods, consider sensitivity analyses.

## Publication and Reporting Issues

### Pitfall 36: Selective Reporting
**Problem:** Only reporting significant results or favorable analyses.

**Consequences:**
- Literature appears more consistent than reality
- Meta-analyses biased
- Wasted research effort

**Solutions:**
- Preregistration
- Report all analyses
- Use reporting guidelines (CONSORT, PRISMA, etc.)

### Pitfall 37: Rounding to p < .05
**Problem:** Reporting exact p-values selectively (e.g., p = .049 but p < .05 for .051).

**Why problematic:** Obscures values near threshold, enables p-hacking detection evasion.

**Better:** Always report exact p-values.

### Pitfall 38: No Data Sharing
**Problem:** Not making data available for verification or reanalysis.

**Consequences:**
- Can't verify results
- Can't include in meta-analyses
- Hinders scientific progress

**Best practice:** Share data unless privacy concerns prohibit.

## Cross-Validation and Generalization

### Pitfall 39: No Cross-Validation
**Problem:** Testing model on same data used to build it.

**Consequence:** Overly optimistic performance estimates.

**Solutions:**
- Split data (train/test)
- K-fold cross-validation
- Independent validation sample

### Pitfall 40: Data Leakage
**Problem:** Information from test set leaking into training.

**Examples:**
- Normalizing before splitting
- Feature selection on full dataset
- Including temporal information

**Consequence:** Inflated performance metrics.

**Prevention:** All preprocessing decisions made using only training data.

## Meta-Analysis Pitfalls

### Pitfall 41: Apples and Oranges
**Problem:** Combining studies with different designs, populations, or measures.

**Balance:** Need homogeneity but also comprehensiveness.

**Solutions:**
- Clear inclusion criteria
- Subgroup analyses
- Meta-regression for moderators

### Pitfall 42: Ignoring Publication Bias
**Problem:** Published studies overrepresent significant results.

**Consequences:** Overestimated effects in meta-analyses.

**Detection:**
- Funnel plots
- Trim-and-fill
- PET-PEESE
- P-curve analysis

**Solutions:**
- Include unpublished studies
- Register reviews
- Use bias-correction methods

## General Best Practices

1. **Preregister studies** - Distinguish confirmatory from exploratory
2. **Report transparently** - All analyses, not just significant ones
3. **Check assumptions** - Don't blindly apply tests
4. **Use appropriate tests** - Match test to data and design
5. **Report effect sizes** - Not just p-values
6. **Consider practical significance** - Not just statistical
7. **Replicate findings** - One study is rarely definitive
8. **Share data and code** - Enable verification
9. **Use confidence intervals** - Show uncertainty
10. **Think causally carefully** - Most research is correlational

### Engineering Statistical Pitfalls

| Pitfall | Description | Example | Solution |
|---------|-------------|---------|----------|
| **Ignoring spatial autocorrelation** | Treating spatially correlated measurements as independent | Using 50 strain gauge readings from one specimen as n=50 independent samples | Account for spatial correlation; use effective sample size |
| **Wrong distribution assumption** | Assuming normality for inherently non-normal data | Wind speed (Weibull), earthquake intensity (lognormal), strength (Weibull) | Test distribution fit; use appropriate distributions |
| **Ignoring load combination statistics** | Treating load combinations as additive of maxima | Adding maximum dead load + maximum live load + maximum wind | Use Turkstra's rule or load combination theory; recognize that maxima don't occur simultaneously |
| **Extreme value misuse** | Applying Gaussian statistics to extreme events | Using mean+3σ for 50-year return period wind | Use Gumbel/GEV distribution; fit to annual maxima |
| **Censoring in testing** | Ignoring run-out specimens (no failure at maximum load) | Excluding specimens that didn't fail from strength analysis | Use Weibull analysis with censored data (maximum likelihood) |
| **Size effect neglect** | Treating strength as size-independent | Using small cylinder strength for large structural member design | Apply Bažant size effect law: σ_N = f'_c / √(1 + D/D₀) |
| **Uncertainty propagation neglect** | Reporting final result without uncertainty bounds | "Safety factor = 2.3" without confidence interval | Propagate input uncertainties to output; report confidence intervals |
| **Multiple comparisons in multi-specimen testing** | Not adjusting for multiple tests | Testing 10 specimens and claiming "significant" improvement for the best one | Apply Bonferroni or FDR correction; pre-register hypotheses |
| **Regression on limited range** | Extrapolating beyond data range | Using 5-point calibration curve to predict at 100× concentration | Report prediction interval; avoid extrapolation beyond 2× range |
| **Ignoring measurement uncertainty** | Using raw instrument readings without calibration uncertainty | Reporting strain to 1 με when gauge accuracy is ±5 με | Include instrument uncertainty in analysis; report combined uncertainty |

---

## Engineering Uncertainty Quantification

### Uncertainty Quantification Frameworks

**Monte Carlo Simulation:**
- [ ] Input distributions defined (normal, lognormal, uniform, etc.)
- [ ] Correlation between input variables accounted for
- [ ] Number of samples sufficient for convergence (typically ≥10,000)
- [ ] Output distribution characterized (mean, std, percentiles)
- [ ] Sensitivity analysis (Sobol indices, tornado diagrams) performed

**Bayesian Updating:**
- [ ] Prior distribution justified (literature, expert judgment, or non-informative)
- [ ] Likelihood function correctly specified
- [ ] Posterior distribution computed (analytical or MCMC)
- [ ] Convergence diagnostics reported (R-hat, effective sample size)
- [ ] Posterior predictive checks performed

**Polynomial Chaos Expansion:**
- [ ] Basis functions appropriate for input distributions
- [ ] Order of expansion sufficient for accuracy
- [ ] Coefficients estimated (regression or projection)
- [ ] Validation against Monte Carlo reference

**Interval Analysis:**
- [ ] Input intervals defined with justification
- [ ] Propagation method specified (sampling, optimization, affine arithmetic)
- [ ] Output intervals reported with bounds

### Structural Reliability Analysis

**First-Order Reliability Method (FORM):**
- [ ] Limit state function clearly defined
- [ ] Random variables identified with distributions
- [ ] Reliability index (β) and failure probability (Pf) reported
- [ ] Design point identified
- [ ] Sensitivity factors reported

**Importance Sampling:**
- [ ] Sampling density centered at design point
- [ ] Number of samples sufficient
- [ ] Coefficient of variation of estimate reported

### Performance Gap Analysis (Buildings)

**Design vs. Actual Performance:**
- [ ] Comparison between predicted and measured energy use
- [ ] Performance gap quantified (absolute and percentage)
- [ ] Contributing factors identified:
  - Construction quality deviations
  - Occupant behavior differences
  - Commissioning inadequacies
  - Modeling assumptions
  - Climate data differences
- [ ] Post-occupancy evaluation conducted

**Rebound Effect:**
- [ ] Direct rebound (increased use due to efficiency) quantified
- [ ] Indirect rebound (spending savings on other energy) discussed
  - Economy-wide rebound considered for policy implications
- [ ] Backfire possibility assessed (>100% rebound)

### Environmental Engineering Specific Uncertainties

**Emission Factor Uncertainty:**
- [ ] Source of emission factor documented (database, measurement, estimation)
- [ ] Uncertainty range of emission factor reported
- [ ] Propagation through calculations demonstrated
- [ ] Sensitivity to emission factor choice tested

**Temporal Resolution Mismatch:**
- [ ] Match between temporal resolution of data and analysis needs
- [ ] Impact of using annual vs. hourly vs. sub-hourly data discussed
- [ ] Seasonal variation captured adequately

**Allocation Sensitivity (LCA):**
- [ ] Allocation method justified (mass, economic, physical)
- [ ] Sensitivity to allocation method tested
- [ ] System expansion considered as alternative

**Discount Rate Sensitivity (LCC):**
- [ ] Discount rate justified
- [ ] Sensitivity analysis across range of rates (e.g., 2%, 5%, 8%)
- [ ] Impact on results quantified
