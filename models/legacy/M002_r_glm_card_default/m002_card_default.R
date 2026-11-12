# M002 - Credit card default model (legacy model, simulated)
# Owner : Cards Risk Analytics
# Data  : Default of Credit Card Clients (Taiwan, UCI), cleaned extract
# Use   : probability of default next month for existing card accounts
library(dplyr)

cards <- read.csv("data/clean/taiwan_default_train.csv")
holdout <- read.csv("data/clean/taiwan_default_test.csv")

prepare <- function(df) {
  df %>%
    mutate(
      # utilisation: latest statement balance over the credit limit
      util = bill_amt1 / pmax(limit_bal, 1),
      # education: 1 graduate school, 2 university, 3 high school, 4 other
      education = ifelse(education %in% c(1, 2, 3), education, 4),
      # reference level: university (the largest group)
      education = relevel(factor(education), ref = "2")
    )
}

cards <- prepare(cards)
holdout <- prepare(holdout)

m002 <- glm(
  default_next_month ~ limit_bal + util + pay_0 + pay_2 + age + education,
  family = binomial(link = "logit"),
  data = cards
)
summary(m002)

# exports handed to the Model Risk Factory
holdout$pd_legacy <- predict(m002, newdata = holdout, type = "response")
write.csv(data.frame(term = names(coef(m002)), estimate = coef(m002)), "coefficients.csv", row.names = FALSE)
write.csv(holdout[, c("id", "pd_legacy", "default_next_month")], "legacy_scores.csv", row.names = FALSE)
