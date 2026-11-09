# M002 - Credit card default model (synthetic legacy model)
# Taiwan credit card clients data, 6-month default
library(dplyr)

cards <- read.csv("data/clean/taiwan_default_train.csv")   # pre-cleaned
cards$util <- cards$bill_amt1 / pmax(cards$limit_bal, 1)

m002 <- glm(default_next_month ~ limit_bal + util + pay_0 + pay_2 + age + factor(education),
            family = binomial(link = "logit"), data = cards)

summary(m002)
cards$pd <- predict(m002, newdata = cards, type = "response")
