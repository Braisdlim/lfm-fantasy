# Model contract

The active models are transparent statistical/rule-based models. The public demo uses the same implementation with a real sporting snapshot and an example league. It is not a benchmark of real future performance.

## Bid and purchase decision

`analysis/bids.py` estimates the reference winning premium from past completed winning bids. It uses price bands, momentum adjustments and minimum sample sizes. Losing bids are absent: a 70th percentile does not imply a 70% chance of winning the next auction.

`analysis/recommend.py` compares that reference with estimated resale plus marginal sporting value, minus a required margin. Cash and squad feasibility constrain the result. Verdicts include `pujar`, `no_pujar`, `sin_saldo`, `sin_datos`, `vender` and `aguantar`.

The system resale multiplier and euros-per-point conversion are inherited, league-specific measurements/assumptions. They must be recalibrated for a new context. Every reason should retain its numerical value, sample/source or assumption; a missing sample must not become certainty.

## Sporting value and lineup

`points.py` uses past gameweek totals, positional baselines, opponent context and estimated starting probability. Unknown probability uses an explicit fallback and is still reported as unknown. Official injuries/suspensions/out-of-league states and external absence flags constrain selection.

`eleven.py` evaluates the seven formations supported by the game. It maximises estimated points for the next unlocked gameweek and persists each own player's computed points, selection and captured-current-lineup flag. A later manual game change is not known until the next lineup capture.

## Forecasts and descriptive views

`fixtures.py` uses attack/defence strengths shrunk toward the league baseline and a Poisson goal model. Availability estimates are current-source observations, not forecasts of injuries weeks ahead. `bargains.py` is a descriptive comparison against similar-price players, not a promise of future gains. Rival cash is reconstructed with explicit uncertainty.

## Validation rule

Model changes require forward-only evaluation against simple baselines. Training prices/outcomes must precede the prediction cutoff. Demo success demonstrates plumbing and guardrails; it does not establish calibration or out-of-sample accuracy. The active points model remains based on total points; incomplete detailed statistics do not justify switching it to a component model.

Historical fitted constants and comments in this public snapshot record observations from one private use case. The private raw evidence is not redistributed, so an independent reader cannot reproduce those particular production backtests from the demo.
