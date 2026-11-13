# SIM_R_RED_GINI_LT_030: simulated probability of default model.
# Owner: Synthetic Validation Tests. Target: default_flag, one means default.
# Use: local testing only; all records are synthetic and contain no customer information.
# Frozen production parameters are supplied in coefficients.json. Do not refit them for the parity test.
# The reference fit below is diagnostic; exported scores use the frozen formula.
# Limitations: no real portfolio evidence or independent native-engine reference scores.
# The age_band groups are matched replicas for controlled fairness testing, not independent customers.
# Governance: H1 documentation approval and independent H2 validation sign-off are required.
# Monitoring compares future batches with the registered healthy baseline.

fit_reference <- function(development) {
  glm(default_flag ~ risk_driver + utilisation,
      family = binomial(link = "logit"), data = development)
}

score <- function(input) {
  eta <- -0.1 + 0.15 * input$risk_driver + 0.2 * input$utilisation
  plogis(eta)
}

input <- read.csv("input_sample.csv")
legacy <- data.frame(id = input$id, pd_legacy = score(input))
write.csv(legacy, "legacy_scores.csv", row.names = FALSE)
