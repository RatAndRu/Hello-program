package com.example.budgetlife

object Demo {
    fun build(): AppState {
        val s = AppState.defaults(); val today = Dates.today(); val ym = Dates.nowYM()
        fun cat(name: String, kind: String) = s.categories.firstOrNull { it.name == name && it.kind == kind }
        val card = Account(uid("acc"), "Основная карта", "card", "RUB", 84250.0, "#38c3f5", "CreditCard", null, true, false, 1)
        val cash = Account(uid("acc"), "Наличные", "cash", "RUB", 12500.0, "#34e5b0", "Banknote", null, true, false, 2)
        val savings = Account(uid("acc"), "Накопительный счёт", "savings", "RUB", 326000.0, "#10d19a", "PiggyBank", null, true, false, 3, InterestConfig(true, 14.5, "monthly", 5, "compound", null, 15000.0, 6, ym, null, null, null))
        val deposit = Account(uid("acc"), "Вклад «Годовой»", "deposit", "RUB", 500000.0, "#8b5cf6", "Landmark", null, true, false, 4, InterestConfig(true, 16.0, "endOfTerm", null, "compound", null, 0.0, 5, null, null, Dates.parse(today).minusMonths(2).toString(), Dates.parse(today).plusMonths(10).toString()))
        val broker = Account(uid("acc"), "Брокерский счёт", "broker", "RUB", 218400.0, "#60a5fa", "TrendingUp", null, true, false, 5)
        val usd = Account(uid("acc"), "Долларовый счёт", "card", "USD", 1240.0, "#f59e0b", "Wallet", null, true, false, 6)
        val creditAcc = Account(uid("acc"), "Кредитная карта", "credit", "RUB", 0.0, "#fb7d8e", "CreditCard", null, false, false, 7, creditLimit = 150000.0)
        s.accounts += listOf(card, cash, savings, deposit, broker, usd, creditAcc)
        s.incomes += IncomeSource(uid("inc"), "Работа · ООО «Пример»", "salary", card.id, "RUB", 148000.0, false, mutableListOf(PayDay(uid("pd"), "Аванс", 25, .4, null, "prevWorkday"), PayDay(uid("pd"), "Зарплата", 10, .6, null, "prevWorkday")), Dates.addYM(ym, -12), null, cat("Зарплата", "income")?.id, null, true, true, 13.0, mutableMapOf(), 1)
        s.incomes += IncomeSource(uid("inc"), "Фриланс", "freelance", card.id, "RUB", 36000.0, true, mutableListOf(PayDay(uid("pd"), "Оплата проектов", -1, 1.0, null, "prevWorkday")), Dates.addYM(ym, -8), null, cat("Фриланс", "income")?.id, null, true, false, 0.0, mutableMapOf(), 2)
        listOf(
            Triple("Музыка", 799.0, "Подписки"), Triple("Облачное хранилище", 299.0, "Подписки"), Triple("Спортзал", 2900.0, "Спорт"), Triple("Интернет", 890.0, "Связь и интернет")
        ).forEachIndexed { i, (name, amount, category) -> s.subscriptions += Subscription(uid("sub"), name, amount, "RUB", 1, "month", Dates.parse(today).minusDays((4 + i * 3).toLong()).toString(), null, cat(category, "expense")?.id, card.id, true, true, 2, null, null, mutableListOf(), listOf("#8b5cf6", "#38c3f5", "#4ade80", "#34e5b0")[i], "Repeat") }
        s.credits += Credit(uid("cr"), "Рассрочка на ноутбук", "installment", card.id, "RUB", 84000.0, 0.0, 12, Dates.parse(today).minusMonths(4).toString(), 15, "annuity", 56000.0, null, null, null, null, null, null, null, "min", null, 0.0, null, "#60a5fa", true)
        s.credits += Credit(uid("cr"), "Кредитная карта", "credit_card", creditAcc.id, "RUB", 0.0, 24.9, 12, Dates.parse(today).minusMonths(6).toString(), 20, "annuity", null, 150000.0, 18450.0, 55, 1, 20, 5.0, 500.0, "full", null, 0.0, null, "#fb7d8e", true)
        val samples = listOf(
            Triple("Продукты", -6840.0, "Еда и продукты"), Triple("Аренда квартиры", -45000.0, "Жильё"), Triple("Транспорт", -2360.0, "Транспорт"), Triple("Кафе с друзьями", -3180.0, "Кафе и рестораны"), Triple("Аптека", -1740.0, "Здоровье")
        )
        samples.forEachIndexed { i, (title, amount, category) -> s.transactions += Transaction(uid("tx"), Dates.parse(today).minusDays((i * 3 + 1).toLong()).toString(), amount, "RUB", card.id, null, cat(category, "expense")?.id, title, null, "expense", "done", "manual", null, null, null, null, null, null, mutableListOf()) }
        s.settings.demoLoaded = true; s.settings.onboarded = true
        return s
    }
}
