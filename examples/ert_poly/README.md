# ERT Poly Example

This is a direct port of the classic ERT (Ensemble Reservoir Tool) [poly_example](https://github.com/equinor/ert/tree/main/test-data/ert/poly_example) adapted for the GERT orchestration framework.

## The Model

The forward model evaluates a simple second-degree polynomial:

$$y = A \cdot x^2 + B \cdot x + C$$

## The Goal

We want to determine the coefficients $A, B, C$.

The observations are generated using a "true" model where $A=0.5, B=1.0, C=3.0$, combined with some random noise. We observe the values of $y$ at $x \in \{0, 2, 4, 6, 8\}$.

We initialize an ensemble of 20 realizations with Gaussian priors far away from the true values, and we use the Ensemble Information Filter (EnIF) plugin to assimilate the data over 5 iterations and update the parameters.

## Running

Ensure the GERT server is running:
```bash
gert server
```

Then submit the experiment:
```bash
gert run examples/ert_poly/experiment.json
```
