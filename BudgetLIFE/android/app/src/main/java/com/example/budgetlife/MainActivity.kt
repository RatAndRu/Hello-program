package com.example.budgetlife

import android.app.Activity
import android.app.AlertDialog
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.os.Bundle
import android.text.InputType
import android.view.View
import android.view.ViewGroup
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.HorizontalScrollView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.Spinner
import android.widget.TextView
import android.widget.Toast
import org.json.JSONObject
import java.time.LocalDate
import kotlin.math.abs

class MainActivity : Activity() {
    private lateinit var store: BudgetStore
    private lateinit var state: AppState
    private lateinit var content: LinearLayout
    private lateinit var pageTitle: TextView
    private lateinit var pageHint: TextView
    private lateinit var ratesButton: Button
    private val pages = listOf("Обзор", "Календарь", "Доходы", "Расходы", "Счета", "Подписки", "Кредиты", "Конвертер", "Аналитика", "Настройки")
    private val hints = listOf("Сводка на сегодня", "Выплаты и списания по дням", "Зарплаты, авансы, подработки", "Что и когда планируем тратить", "Балансы, проценты, пополнения", "Регулярные списания", "Платежи и беспроцентный период", "Актуальные курсы валют", "Графики и отчёты", "Данные, курсы, импорт")
    private var page = 0
    private var selectedDate = Dates.today()
    private var calendarYM = Dates.nowYM()
    private var dashboardMonths = 6
    private var analyticsMonths = 6
    private var expenseQuery = ""
    private var expenseStatus = "all"
    private var expenseCategoryId: String? = null
    private var expenseAccountId: String? = null
    private var convAmount = "100"
    private var convFrom = "USD"
    private var convTo = "RUB"
    private var rendering = false

    private fun pal() = palette(state)
    private fun engine() = Engine(state)
    private fun baseMoney(v: Double, signed: Boolean = false, compact: Boolean = false) = Money.fmt(v, state.settings.baseCurrency, state, signed, compact)
    private fun money(v: Double, cur: String, signed: Boolean = false) = Money.fmt(v, cur, state, signed)
    private fun accName(id: String?) = state.accounts.firstOrNull { it.id == id }?.name ?: "Без счёта"
    private fun catName(id: String?) = state.categories.firstOrNull { it.id == id }?.name ?: "Без категории"
    private fun toast(s: String) = Toast.makeText(this, s, Toast.LENGTH_SHORT).show()
    private fun save(renderAfter: Boolean = true) { store.save(state); if (renderAfter) render() }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        store = BudgetStore(this)
        state = store.load()
        buildShell()
        render()
        val stale = state.rates == null || System.currentTimeMillis() - (state.rates?.fetchedAt ?: 0L) > 12 * 3600 * 1000L
        if (stale && state.settings.ratesProvider != "manual") refreshRates(silent = true)
    }

    private fun buildShell() {
        val p = pal(); val root = findViewById<FrameLayout>(R.id.root); root.setBackgroundColor(p.bg)
        val shell = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        root.addView(shell)
        val header = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = android.view.Gravity.CENTER_VERTICAL; setPadding(dp(14), dp(10), dp(14), dp(8)); setBackgroundColor(p.bg) }
        val logo = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        val brand = row(this); brand.addView(text(this, "Budget", 19f, p.text, true)); brand.addView(text(this, "LIFE", 19f, p.brand, true))
        logo.addView(brand); logo.addView(text(this, "ПЛАНИРОВЩИК БЮДЖЕТА", 9f, p.muted, true))
        header.addView(logo); header.addView(spacer(this))
        ratesButton = actionButton(this, p, if (state.rates == null) "Нет курсов" else "Курсы")
        ratesButton.setOnClickListener { refreshRates(false) }; header.addView(ratesButton)
        val eye = actionButton(this, p, if (state.settings.hideBalances) "🙈" else "👁"); eye.setOnClickListener { state.settings.hideBalances = !state.settings.hideBalances; save() }; header.addView(eye)
        val plus = actionButton(this, p, "＋ Операция", true); plus.setOnClickListener { showTransactionForm(null) }; header.addView(plus)
        shell.addView(header)
        val titleBlock = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dp(16), dp(2), dp(16), dp(8)) }
        pageTitle = text(this, pages[0], 24f, p.text, true); pageHint = text(this, hints[0], 12f, p.muted)
        titleBlock.addView(pageTitle); titleBlock.addView(pageHint); shell.addView(titleBlock)
        val scroll = ScrollView(this).apply { layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f) }
        content = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dp(14), dp(4), dp(14), dp(18)) }
        scroll.addView(content); shell.addView(scroll)
        val navScroll = HorizontalScrollView(this).apply { isHorizontalScrollBarEnabled = false; setBackgroundColor(p.card); layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT) }
        val nav = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; setPadding(dp(8), dp(8), dp(8), dp(10)) }
        val icons = listOf("⌂", "📅", "↗", "🧾", "💼", "↻", "💳", "⇄", "📊", "⚙")
        pages.forEachIndexed { i, label -> val b = chip(this, p, "${icons[i]} $label", i == page); b.setOnClickListener { page = i; render() }; nav.addView(b) }
        navScroll.addView(nav); shell.addView(navScroll)
    }

    private fun render() {
        rendering = true
        val p = pal(); findViewById<View>(R.id.root).setBackgroundColor(p.bg)
        pageTitle.text = pages[page]; pageTitle.setTextColor(p.text); pageHint.text = hints[page]; pageHint.setTextColor(p.muted)
        ratesButton.text = if (state.rates == null) "Нет курсов" else "Курсы: ${Dates.fmtShort(state.rates!!.date)}"
        content.removeAllViews()
        when (page) {
            0 -> dashboard(); 1 -> calendarPage(); 2 -> incomesPage(); 3 -> expensesPage(); 4 -> accountsPage(); 5 -> subscriptionsPage(); 6 -> creditsPage(); 7 -> converterPage(); 8 -> analyticsPage(); else -> settingsPage()
        }
        rendering = false
    }

    private fun heading(title: String, subtitle: String? = null, actionLabel: String? = null, action: (() -> Unit)? = null) {
        val p = pal(); val r = row(this); val col = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f) }
        col.addView(text(this, title, 18f, p.text, true)); if (subtitle != null) col.addView(text(this, subtitle, 12f, p.muted)); r.addView(col)
        if (actionLabel != null && action != null) { val b = actionButton(this, p, actionLabel, true); b.setOnClickListener { action() }; r.addView(b) }
        content.addView(r); content.addView(vspace(this, 10))
    }
    private fun stat(label: String, value: String, note: String? = null, color: Int = pal().text): LinearLayout { val p = pal(); val c = card(this, p); c.addView(text(this, label.uppercase(), 10f, p.muted, true)); c.addView(text(this, value, 19f, color, true)); if (note != null) c.addView(text(this, note, 11f, p.muted)); return c }
    private fun addTwoStats(a: LinearLayout, b: LinearLayout) { val r = row(this); a.layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f).apply { setMargins(0, 0, dp(6), dp(12)) }; b.layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f).apply { setMargins(dp(6), 0, 0, dp(12)) }; r.addView(a); r.addView(b); content.addView(r) }
    private fun empty(title: String, note: String, actionLabel: String? = null, action: (() -> Unit)? = null) { val p = pal(); val c = card(this, p); c.gravity = android.view.Gravity.CENTER; c.addView(text(this, title, 17f, p.text, true, true)); c.addView(text(this, note, 13f, p.muted, false, true)); if (actionLabel != null && action != null) { val b = actionButton(this, p, actionLabel, true); b.setOnClickListener { action() }; c.addView(b) }; content.addView(c) }
    private fun eventRow(e: CashEvent, showDate: Boolean = true) {
        val p = pal(); val c = card(this, p); val r = row(this)
        val dot = View(this).apply { background = rounded(try { Color.parseColor(e.color ?: "#38c3f5") } catch (_: Exception) { p.brand }, 999, this@MainActivity); layoutParams = LinearLayout.LayoutParams(dp(10), dp(10)).apply { setMargins(0, 0, dp(10), 0) } }
        r.addView(dot); val col = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f) }
        col.addView(text(this, e.title, 14f, p.text, true)); col.addView(text(this, "${if (showDate) Dates.fmtShort(e.date) + " · " else ""}${accName(e.accountId)} · ${catName(e.categoryId)} · ${if (e.status == "done") "факт" else "план"}${if (e.tentative) " · уточнить" else ""}", 11f, p.muted)); if (!e.note.isNullOrBlank()) col.addView(text(this, e.note, 11f, p.muted))
        r.addView(col); r.addView(text(this, money(e.amount, e.currency, true), 14f, if (e.amount >= 0) p.mint else p.rose, true)); c.addView(r); c.setOnClickListener { showEventDialog(e) }; content.addView(c)
    }

    private fun dashboard() {
        val p = pal()
        if (state.accounts.isEmpty()) {
            val c = card(this, p); c.addView(text(this, "Добро пожаловать в BudgetLIFE", 21f, p.text, true)); c.addView(text(this, "Ваш личный центр управления деньгами. Все данные хранятся только на телефоне.", 13f, p.muted)); content.addView(c)
            addTwoStats(stat("Демо-данные", "Готовый сценарий", "7 счетов, доходы, подписки и кредиты", p.brand), stat("Чистый лист", "Начать самому", "Создадим первый счёт", p.mint))
            val r = row(this); val demo = actionButton(this, p, "✨ Загрузить демо", true); demo.setOnClickListener { state = Demo.build(); save() }; val clean = actionButton(this, p, "Создать первый счёт"); clean.setOnClickListener { showAccountForm(null) }; r.addView(demo); r.addView(clean); content.addView(r); return
        }
        val eng = engine(); val today = Dates.today(); val (from, to) = Dates.financialMonthBounds(today, state.settings.monthStartDay)
        val proj = eng.project(from, Dates.parse(to).plusMonths(12).toString())
        val periodEvents = proj.events.filter { it.date in from..to }; val (inc, exp, net) = eng.totals(periodEvents)
        val doneEvents = periodEvents.filter { it.status == "done" }; val (doneInc, doneExp, _) = eng.totals(doneEvents)
        val totalBalance = state.accounts.filter { it.includeInTotal && !it.archived }.sumOf { RatesMath.convert(it.balance, it.currency, state.settings.baseCurrency, state) }
        val forecast = proj.days.lastOrNull { it.date <= to }?.balance ?: totalBalance
        addTwoStats(stat("Общий баланс", baseMoney(totalBalance), "на всех учитываемых счетах"), stat("Прогноз на конец периода", baseMoney(forecast), "${Dates.fmtShort(from)} — ${Dates.fmtShort(to)}", if (forecast >= totalBalance) p.mint else p.amber))
        addTwoStats(stat("Доходы периода", baseMoney(inc), "факт: ${baseMoney(doneInc)}", p.mint), stat("Расходы периода", baseMoney(exp), "факт: ${baseMoney(doneExp)}", p.rose))
        val passive = state.accounts.sumOf { RatesMath.convert(eng.estimateMonthlyInterest(it), it.currency, state.settings.baseCurrency, state) }
        addTwoStats(stat("Чистый поток", baseMoney(net, true), "доходы минус расходы", if (net >= 0) p.mint else p.rose), stat("Пассивный доход", baseMoney(passive), "проценты по счетам в месяц", p.brand))
        val chartCard = card(this, p); chartCard.addView(text(this, "Динамика баланса", 15f, p.text, true)); val chips = row(this); listOf(1, 3, 6, 12).forEach { m -> val b = chip(this, p, "$m мес", dashboardMonths == m); b.setOnClickListener { dashboardMonths = m; render() }; chips.addView(b) }; chartCard.addView(chips)
        val longProj = eng.project(today, Dates.parse(today).plusMonths(dashboardMonths.toLong()).toString())
        val monthly = (0..dashboardMonths).map { off -> val ym = Dates.addYM(Dates.nowYM(), off.toLong()); val day = longProj.days.filter { Dates.ymOf(it.date) == ym }.lastOrNull(); Dates.monthLabel(ym).take(3) to (day?.balance ?: totalBalance) }
        val chart = LineChartView(this, monthly.map { it.second }, monthly.map { it.first }, p, p.brand); chart.layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(190)); chartCard.addView(chart); proj.min?.let { chartCard.addView(text(this, "Минимум: ${baseMoney(it.first)} · ${Dates.fmtShort(it.second)}", 11f, p.amber)) }; content.addView(chartCard)
        heading("Ближайшие события", "Что произойдёт в ближайшие 30 дней")
        eng.buildEvents(today, Dates.parse(today).plusDays(30).toString()).filter { it.status == "planned" }.take(8).forEach { eventRow(it) }
        heading("Структура расходов периода")
        val cats = eng.categoryBreakdown(periodEvents, false); if (cats.isEmpty()) empty("Пока нет расходов", "Добавьте расход или запланируйте операцию") else cats.take(7).forEach { (cat, value, _) -> val c = card(this, p); val r = row(this); r.addView(text(this, cat?.name ?: "Без категории", 13f, p.text, true)); r.addView(spacer(this)); r.addView(text(this, baseMoney(value), 13f, p.rose, true)); c.addView(r); c.addView(progress(this, p, if (exp == 0.0) 0.0 else value / exp, try { Color.parseColor(cat?.color ?: "#fb7185") } catch (_: Exception) { p.rose })); content.addView(c) }
        val subMonthly = state.subscriptions.filter { it.active }.sumOf { RatesMath.convert(it.amount * 30.4375 / Dates.cycleDays(it.every, it.unit), it.currency, state.settings.baseCurrency, state) }
        val nextCredit = state.credits.filter { it.active }.flatMap { cr -> CreditMath.loanSchedule(cr).firstOrNull { it.date >= today }?.let { listOf(cr.name to it.date) } ?: emptyList() }.minByOrNull { it.second }
        addTwoStats(stat("Подписки", baseMoney(subMonthly) + " / мес", "${state.subscriptions.count { it.active }} активных"), stat("Следующий кредитный платёж", nextCredit?.let { Dates.fmtShort(it.second) } ?: "—", nextCredit?.first ?: "кредитов нет", p.amber))
    }

    private fun calendarPage() {
        val p = pal(); val ym = calendarYM; val (from, to) = Dates.monthBounds(ym); val eng = engine(); val events = eng.buildEvents(Dates.parse(from).minusDays(7).toString(), Dates.parse(to).plusDays(7).toString())
        val r = row(this); val prev = actionButton(this, p, "‹"); prev.setOnClickListener { calendarYM = Dates.addYM(calendarYM, -1); render() }; val todayBtn = actionButton(this, p, "Сегодня"); todayBtn.setOnClickListener { calendarYM = Dates.nowYM(); selectedDate = Dates.today(); render() }; val next = actionButton(this, p, "›"); next.setOnClickListener { calendarYM = Dates.addYM(calendarYM, 1); render() }; r.addView(prev); r.addView(text(this, Dates.monthLabel(ym), 18f, p.text, true, true).apply { layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f) }); r.addView(todayBtn); r.addView(next); content.addView(r); content.addView(vspace(this, 8))
        val byDate = events.groupBy { it.date }; val first = Dates.parse(from); val startOffset = (first.dayOfWeek.value - state.settings.firstDayOfWeek + 7) % 7; val gridStart = first.minusDays(startOffset.toLong()); val cells = (0 until 42).map { off -> val date = gridStart.plusDays(off.toLong()).toString(); val dayEvents = byDate[date].orEmpty(); CalendarCellData(date, Dates.ymOf(date) == ym, date == Dates.today(), dayEvents.filter { it.amount > 0 && it.kind != "transfer" }.sumOf { RatesMath.convert(it.amount, it.currency, state.settings.baseCurrency, state) }, dayEvents.filter { it.amount < 0 }.sumOf { RatesMath.convert(-it.amount, it.currency, state.settings.baseCurrency, state) }, dayEvents.size) }
        val cal = CalendarView(this, cells, p, { v -> baseMoney(v, compact = true) }) { date -> selectedDate = date; render() }; cal.select(selectedDate); val cc = card(this, p); cc.addView(cal); content.addView(cc)
        val dayEvents = byDate[selectedDate].orEmpty(); val (inc, exp, _) = eng.totals(dayEvents); val balance = eng.project(selectedDate, selectedDate, startFrom = selectedDate).days.lastOrNull()?.balance
        heading("${Dates.fmt(selectedDate)} · ${Dates.humanRelative(selectedDate)}", "Доходы ${baseMoney(inc)} · расходы ${baseMoney(exp)}" + (balance?.let { " · баланс на конец дня ${baseMoney(it)}" } ?: ""), "＋ Операция") { showTransactionForm(null, selectedDate) }
        if (dayEvents.isEmpty()) empty("Событий нет", "Нажмите «Операция», чтобы добавить доход или расход на этот день") else dayEvents.forEach { eventRow(it, false) }
    }

    private fun incomesPage() {
        val p = pal(); val eng = engine(); val ym = Dates.nowYM(); val monthly = state.incomes.filter { it.active }.sumOf { src -> eng.incomeMonthPayments(src, ym).sumOf { RatesMath.convert(it.third, src.currency, state.settings.baseCurrency, state) } }
        addTwoStats(stat("Доход в этом месяце", baseMoney(monthly), Dates.monthLabel(ym), p.mint), stat("Источников", state.incomes.count { it.active }.toString(), "всего ${state.incomes.size}"))
        heading("Источники дохода", "Несколько дней выплат, плавающие даты, налог и корректировки по месяцам", "＋ Доход") { showIncomeForm(null) }
        if (state.incomes.isEmpty()) { empty("Нет источников дохода", "Добавьте зарплату, аванс, фриланс или другой доход", "Добавить доход") { showIncomeForm(null) }; return }
        for (src in state.incomes.sortedBy { it.order }) {
            val c = card(this, p); val r = row(this); val col = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f) }
            col.addView(text(this, src.name, 16f, p.text, true)); col.addView(text(this, "${money(src.amount, src.currency)} / мес · ${accName(src.accountId)} · ${if (src.active) "активен" else "выключен"}${if (src.variable) " · сумма меняется" else ""}", 12f, p.muted)); r.addView(col); r.addView(text(this, money(eng.incomeMonthPayments(src, ym).sumOf { it.third }, src.currency), 15f, p.mint, true)); c.addView(r)
            val payments = eng.incomeMonthPayments(src, ym); if (payments.isNotEmpty()) c.addView(text(this, payments.joinToString(" · ") { "${it.first.label}: ${Dates.fmtShort(it.second)} — ${money(it.third, src.currency)}" }, 12f, p.muted))
            val nextMonths = (0..5).map { off -> val m = Dates.addYM(ym, off.toLong()); m to eng.incomeMonthPayments(src, m).sumOf { it.third } }
            c.addView(text(this, "6 месяцев: " + nextMonths.joinToString(" · ") { "${Dates.monthLabel(it.first).take(3)} ${money(it.second, src.currency, false)}" }, 11f, p.muted))
            val br = row(this); val edit = actionButton(this, p, "Изменить"); edit.setOnClickListener { showIncomeForm(src) }; val months = actionButton(this, p, "По месяцам"); months.setOnClickListener { showIncomeMonths(src) }; val toggle = actionButton(this, p, if (src.active) "Пауза" else "Включить"); toggle.setOnClickListener { src.active = !src.active; save() }; val del = actionButton(this, p, "Удалить", danger = true); del.setOnClickListener { confirm("Удалить доход «${src.name}»?") { state.incomes.remove(src); state.transactions.removeAll { it.sourceId == src.id }; save() } }; br.addView(edit); br.addView(months); br.addView(toggle); br.addView(del); c.addView(br); content.addView(c)
        }
    }

    private fun expensesPage() {
        val p = pal(); val eng = engine(); val ym = Dates.nowYM(); val (from, to) = Dates.monthBounds(ym); val monthEvents = eng.buildEvents(from, to)
        heading("Лимиты по категориям", "Месячный бюджет и фактические расходы", "＋ Операция") { showTransactionForm(null) }
        val expenseCats = state.categories.filter { it.kind == "expense" }.sortedBy { it.order }
        var anyLimit = false
        for (cat in expenseCats) { val limit = cat.budgetMonthly ?: continue; anyLimit = true; val spent = monthEvents.filter { it.categoryId == cat.id && it.amount < 0 }.sumOf { RatesMath.convert(-it.amount, it.currency, state.settings.baseCurrency, state) }; val c = card(this, p); val r = row(this); r.addView(text(this, cat.name, 14f, p.text, true)); r.addView(spacer(this)); r.addView(text(this, "${baseMoney(spent)} / ${baseMoney(limit)}", 13f, if (spent > limit) p.rose else p.muted, true)); c.addView(r); c.addView(progress(this, p, if (limit == 0.0) 0.0 else spent / limit, if (spent > limit) p.rose else try { Color.parseColor(cat.color) } catch (_: Exception) { p.brand })); c.setOnClickListener { showCategoryForm(cat) }; content.addView(c) }
        if (!anyLimit) empty("Лимиты не заданы", "Откройте категорию в настройках или нажмите на неё здесь после добавления", "Категории") { page = 9; render() }
        heading("Операции", "План и факт, повторения, поиск и фильтры")
        val search = EditText(this).apply { hint = "Поиск по названию или заметке"; setText(expenseQuery); setSingleLine(true); setTextColor(p.text); setHintTextColor(p.muted); background = rounded(p.card2, 14, this@MainActivity, p.line); setPadding(dp(12), dp(10), dp(12), dp(10)) }
        val apply = actionButton(this, p, "Найти", true); apply.setOnClickListener { expenseQuery = search.text.toString(); render() }; val sr = row(this); sr.addView(search.apply { layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f) }); sr.addView(apply); content.addView(sr)
        val chips = row(this); listOf("all" to "Все", "planned" to "План", "done" to "Факт").forEach { (key, label) -> val b = chip(this, p, label, expenseStatus == key); b.setOnClickListener { expenseStatus = key; render() }; chips.addView(b) }; content.addView(chips); content.addView(vspace(this, 8))
        val wideFrom = Dates.parse(from).minusMonths(2).toString(); val wideTo = Dates.parse(to).plusMonths(6).toString(); var events = eng.buildEvents(wideFrom, wideTo)
        events = events.filter { e -> (expenseStatus == "all" || e.status == expenseStatus) && (expenseCategoryId == null || e.categoryId == expenseCategoryId) && (expenseAccountId == null || e.accountId == expenseAccountId) && (expenseQuery.isBlank() || e.title.contains(expenseQuery, true) || (e.note ?: "").contains(expenseQuery, true)) }
        val catsRow = row(this); val allCat = chip(this, p, "Все категории", expenseCategoryId == null); allCat.setOnClickListener { expenseCategoryId = null; render() }; catsRow.addView(allCat); state.categories.take(10).forEach { cat -> val b = chip(this, p, cat.name, expenseCategoryId == cat.id); b.setOnClickListener { expenseCategoryId = cat.id; render() }; catsRow.addView(b) }; val hs = HorizontalScrollView(this); hs.addView(catsRow); content.addView(hs); content.addView(vspace(this, 8))
        if (events.isEmpty()) empty("Ничего не найдено", "Измените фильтры или добавьте операцию") else events.sortedByDescending { it.date }.take(120).forEach { eventRow(it) }
    }

    private fun accountsPage() {
        val p = pal(); val eng = engine(); val total = state.accounts.filter { it.includeInTotal && !it.archived }.sumOf { RatesMath.convert(it.balance, it.currency, state.settings.baseCurrency, state) }; val passive = state.accounts.sumOf { RatesMath.convert(eng.estimateMonthlyInterest(it), it.currency, state.settings.baseCurrency, state) }; val topups = state.accounts.sumOf { RatesMath.convert(it.interest.monthlyTopUp, it.currency, state.settings.baseCurrency, state) }
        addTwoStats(stat("Общий баланс", baseMoney(total), "${state.accounts.count { !it.archived }} счетов"), stat("Пассивный доход", baseMoney(passive), "проценты в месяц", p.mint)); addTwoStats(stat("Пополнения", baseMoney(topups), "автопополнения в месяц", p.brand), stat("В год процентами", baseMoney(passive * 12), "оценка без капитализации", p.amber))
        heading("Мои счета", "Балансы, проценты, капитализация и автопополнение", "＋ Счёт") { showAccountForm(null) }
        val tr = row(this); val transfer = actionButton(this, p, "⇄ Перевод между счетами", true); transfer.setOnClickListener { showTransferForm() }; tr.addView(transfer); content.addView(tr); content.addView(vspace(this, 10))
        if (state.accounts.isEmpty()) { empty("Нет счетов", "Создайте карту, наличные, вклад или накопительный счёт", "Добавить счёт") { showAccountForm(null) }; return }
        val proj = eng.project(Dates.today(), Dates.parse(Dates.today()).plusMonths(12).toString())
        for (acc in state.accounts.sortedBy { it.order }) {
            val c = card(this, p); val r = row(this); val col = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f) }; col.addView(text(this, acc.name, 16f, p.text, true)); col.addView(text(this, "${accountTypeLabel(acc.type)} · ${acc.currency}${if (acc.archived) " · в архиве" else ""}${if (!acc.includeInTotal) " · не в общем балансе" else ""}", 12f, p.muted)); r.addView(col); r.addView(text(this, money(acc.balance, acc.currency), 16f, p.text, true)); c.addView(r)
            if (acc.interest.enabled) { val mi = eng.estimateMonthlyInterest(acc); c.addView(text(this, "Ставка ${Money.percent(acc.interest.annualRate)} · ${money(mi, acc.currency)} / мес · ${money(mi * 12, acc.currency)} / год · ${capitalizationLabel(acc.interest.capitalization)}", 12f, p.mint)) }
            if (acc.interest.monthlyTopUp > 0) c.addView(text(this, "Автопополнение: ${money(acc.interest.monthlyTopUp, acc.currency)} · ${acc.interest.topUpDay}-го числа", 12f, p.brand))
            val future = (1..12).map { off -> val ym = Dates.addYM(Dates.nowYM(), off.toLong()); proj.days.filter { Dates.ymOf(it.date) == ym }.lastOrNull()?.byAccount?.get(acc.id) ?: acc.balance }
            c.addView(text(this, "Прогноз 12 мес: " + future.mapIndexed { i, v -> "${i + 1}:${baseMoney(RatesMath.convert(v, acc.currency, state.settings.baseCurrency, state), compact = true)}" }.joinToString(" "), 11f, p.muted))
            val br = row(this); val edit = actionButton(this, p, "Изменить"); edit.setOnClickListener { showAccountForm(acc) }; val bal = actionButton(this, p, "Баланс"); bal.setOnClickListener { showBalanceDialog(acc) }; val arch = actionButton(this, p, if (acc.archived) "Из архива" else "В архив"); arch.setOnClickListener { acc.archived = !acc.archived; save() }; val del = actionButton(this, p, "Удалить", danger = true); del.setOnClickListener { confirm("Удалить счёт «${acc.name}» и связанные операции?") { state.accounts.remove(acc); state.transactions.removeAll { it.accountId == acc.id || it.toAccountId == acc.id }; state.subscriptions.removeAll { it.accountId == acc.id }; state.credits.removeAll { it.accountId == acc.id }; save() } }; br.addView(edit); br.addView(bal); br.addView(arch); br.addView(del); c.addView(br); content.addView(c)
        }
    }

    private fun subscriptionsPage() {
        val p = pal(); val eng = engine(); val monthly = state.subscriptions.filter { it.active }.sumOf { RatesMath.convert(it.amount * 30.4375 / Dates.cycleDays(it.every, it.unit), it.currency, state.settings.baseCurrency, state) }; val yearly = monthly * 12
        addTwoStats(stat("В месяц", baseMoney(monthly), "эквивалент всех активных подписок", p.rose), stat("В год", baseMoney(yearly), "${state.subscriptions.count { it.active }} активных", p.amber))
        heading("Подписки и регулярные списания", "Произвольный цикл, пробный период, напоминания и история цены", "＋ Подписка") { showSubscriptionForm(null) }
        if (state.subscriptions.isEmpty()) { empty("Нет подписок", "Добавьте сервисы, связь, спортзал или ЖКХ", "Добавить подписку") { showSubscriptionForm(null) }; return }
        val upcoming = eng.buildEvents(Dates.today(), Dates.parse(Dates.today()).plusYears(2).toString()).filter { it.sourceType == "subscription" }.groupBy { it.sourceId }
        for (sub in state.subscriptions) { val next = upcoming[sub.id]?.firstOrNull(); val c = card(this, p); val r = row(this); val col = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f) }; col.addView(text(this, sub.name, 16f, p.text, true)); col.addView(text(this, "${Dates.cycleLabel(sub.every, sub.unit)} · ${accName(sub.accountId)} · ${catName(sub.categoryId)}${if (!sub.active) " · на паузе" else ""}", 12f, p.muted)); if (next != null) col.addView(text(this, "Следующее: ${Dates.fmt(next.date)} (${Dates.humanRelative(next.date)})", 12f, p.brand)); r.addView(col); val amt = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }; amt.addView(text(this, money(sub.amount, sub.currency), 15f, p.rose, true)); amt.addView(text(this, "${baseMoney(RatesMath.convert(sub.amount * 30.4375 / Dates.cycleDays(sub.every, sub.unit), sub.currency, state.settings.baseCurrency, state))}/мес", 11f, p.muted)); r.addView(amt); c.addView(r); val br = row(this); val edit = actionButton(this, p, "Изменить"); edit.setOnClickListener { showSubscriptionForm(sub) }; val toggle = actionButton(this, p, if (sub.active) "Пауза" else "Возобновить"); toggle.setOnClickListener { sub.active = !sub.active; save() }; val del = actionButton(this, p, "Удалить", danger = true); del.setOnClickListener { confirm("Удалить подписку «${sub.name}»?") { state.subscriptions.remove(sub); save() } }; br.addView(edit); br.addView(toggle); br.addView(del); c.addView(br); content.addView(c) }
    }

    private fun creditsPage() {
        val p = pal(); val totalDebt = state.credits.filter { it.active }.sumOf { cr -> RatesMath.convert(if (cr.kind == "credit_card") (cr.used ?: 0.0) else (CreditMath.loanSchedule(cr).lastOrNull()?.let { cr.currentBalance ?: cr.principal } ?: (cr.currentBalance ?: cr.principal)), cr.currency, state.settings.baseCurrency, state) }
        heading("Кредиты и кредитные карты", "Аннуитет, дифференцированный платёж, досрочное погашение и беспроцентный период", "＋ Кредит") { showCreditForm(null) }
        addTwoStats(stat("Текущий долг", baseMoney(totalDebt), "по активным кредитам и картам", p.rose), stat("Активных", state.credits.count { it.active }.toString(), "всего ${state.credits.size}"))
        if (state.credits.isEmpty()) { empty("Нет кредитов", "Добавьте кредит, рассрочку или кредитную карту", "Добавить кредит") { showCreditForm(null) }; return }
        for (cr in state.credits) {
            val c = card(this, p); val r = row(this); val col = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f) }; col.addView(text(this, cr.name, 16f, p.text, true)); col.addView(text(this, "${creditKindLabel(cr.kind)} · ${accName(cr.accountId)} · ${cr.currency}${if (!cr.active) " · закрыт/выключен" else ""}", 12f, p.muted)); r.addView(col); c.addView(r)
            if (cr.kind == "credit_card") { val grace = CreditMath.graceInfo(cr); val debt = cr.used ?: 0.0; c.addView(text(this, "Задолженность: ${money(debt, cr.currency)} из лимита ${money(cr.limit ?: 0.0, cr.currency)} · минимальный платёж ${money(CreditMath.minPayment(cr), cr.currency)}", 13f, p.rose)); if (grace != null) c.addView(text(this, "Беспроцентный период: платёж до ${Dates.fmt(grace.paymentDate)} · осталось ${grace.daysLeft} дн. · внести ${money(grace.debt, cr.currency)}, чтобы не платить проценты", 12f, if (grace.daysLeft <= 5) p.rose else p.mint)); val rows = CreditMath.cardSchedule(cr, Dates.today(), Dates.parse(Dates.today()).plusMonths(6).toString()); if (rows.isNotEmpty()) c.addView(text(this, "План: " + rows.take(6).joinToString(" · ") { "${Dates.fmtShort(it.date)} ${money(it.payment, cr.currency)}" }, 11f, p.muted)) }
            else { val rows = CreditMath.loanSchedule(cr); val next = rows.firstOrNull { it.date >= Dates.today() } ?: rows.firstOrNull(); val totalInterest = rows.sumOf { it.interest }; val totalPayment = rows.sumOf { it.payment + cr.extraPayment }; c.addView(text(this, "Долг: ${money(cr.currentBalance ?: cr.principal, cr.currency)} · ставка ${Money.percent(cr.annualRate)} · ${if (cr.paymentType == "annuity") "аннуитет" else "дифференцированный"}", 13f, p.text)); if (next != null) c.addView(text(this, "Следующий платёж: ${Dates.fmt(next.date)} · ${money(next.payment + cr.extraPayment, cr.currency)} (проценты ${money(next.interest, cr.currency)}, тело ${money(next.principal, cr.currency)})", 12f, p.amber)); c.addView(text(this, "Переплата: ${money(totalInterest, cr.currency)} · всего выплат: ${money(totalPayment, cr.currency)} · закрытие: ${rows.lastOrNull()?.let { Dates.fmt(it.date) } ?: "—"}", 12f, p.muted)); if (rows.isNotEmpty()) { val table = card(this, p); table.addView(text(this, "График платежей", 13f, p.text, true)); rows.take(18).forEach { row -> table.addView(text(this, "${row.index}. ${Dates.fmtShort(row.date)} · платёж ${money(row.payment + cr.extraPayment, cr.currency)} · % ${money(row.interest, cr.currency)} · тело ${money(row.principal, cr.currency)} · остаток ${money(row.balance, cr.currency)}", 11f, p.muted)) }; c.addView(table) } }
            val br = row(this); val edit = actionButton(this, p, "Изменить"); edit.setOnClickListener { showCreditForm(cr) }; val toggle = actionButton(this, p, if (cr.active) "Выключить" else "Включить"); toggle.setOnClickListener { cr.active = !cr.active; save() }; val del = actionButton(this, p, "Удалить", danger = true); del.setOnClickListener { confirm("Удалить кредит «${cr.name}»?") { state.credits.remove(cr); save() } }; br.addView(edit); br.addView(toggle); br.addView(del); c.addView(br); content.addView(c)
        }
    }

    private fun converterPage() {
        val p = pal(); val snap = state.rates
        heading("Конвертер валют", "Курсы ЦБ РФ, ЕЦБ, ExchangeRate API и резервного CDN; ручные курсы имеют приоритет", "↻ Обновить курсы") { refreshRates(false) }
        val c = card(this, p)
        if (snap == null) c.addView(text(this, "Курсы ещё не загружены. Нажмите «Обновить курсы» при включённом интернете. Ручные курсы можно задать в настройках.", 13f, p.amber)) else c.addView(text(this, "Источник: ${providerName(snap.provider)} · дата курса ${Dates.fmt(snap.date)} · обновлено ${java.text.SimpleDateFormat("dd.MM.yyyy HH:mm", Dates.RU).format(java.util.Date(snap.fetchedAt))} · база ${snap.base}", 12f, p.muted))
        val amount = EditText(this).apply { setText(convAmount); inputType = InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_FLAG_DECIMAL; setSingleLine(true); setTextColor(p.text); background = rounded(p.card2, 14, this@MainActivity, p.line); setPadding(dp(12), dp(10), dp(12), dp(10)) }
        c.addView(text(this, "Сумма", 12f, p.muted, true)); c.addView(amount)
        val from = spinner(CurrencyInfo.codes, convFrom); val to = spinner(CurrencyInfo.codes, convTo); val rr = row(this); rr.addView(text(this, "Из", 12f, p.muted)); rr.addView(from); rr.addView(text(this, "В", 12f, p.muted)); rr.addView(to); val swap = actionButton(this, p, "⇄"); swap.setOnClickListener { val f = CurrencyInfo.codes[from.selectedItemPosition]; convFrom = CurrencyInfo.codes[to.selectedItemPosition]; convTo = f; render() }; rr.addView(swap); c.addView(rr)
        val result = text(this, "", 24f, p.text, true); c.addView(result); val detail = text(this, "", 12f, p.muted); c.addView(detail)
        fun calc() { convAmount = amount.text.toString(); convFrom = CurrencyInfo.codes[from.selectedItemPosition]; convTo = CurrencyInfo.codes[to.selectedItemPosition]; val v = Money.parse(convAmount); val out = RatesMath.convert(v, convFrom, convTo, state); result.text = "${money(v, convFrom)} = ${money(out, convTo)}"; val direct = RatesMath.convert(1.0, convFrom, convTo, state); val inverse = RatesMath.convert(1.0, convTo, convFrom, state); detail.text = "1 $convFrom = ${formatRate(direct)} $convTo · 1 $convTo = ${formatRate(inverse)} $convFrom" + if (!RatesMath.hasRate(convFrom, convTo, state)) " · нет курса — сумма показана как есть" else ""; }
        val calcBtn = actionButton(this, p, "Пересчитать", true); calcBtn.setOnClickListener { calc() }; c.addView(calcBtn); calc(); content.addView(c)
        val hist = store.pairHistory(convFrom, convTo, 30); if (hist.size > 1) { val hc = card(this, p); hc.addView(text(this, "Динамика пары $convFrom → $convTo", 14f, p.text, true)); val spark = LineChartView(this, hist, hist.indices.map { "" }, p, p.brand); spark.layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(120)); hc.addView(spark); content.addView(hc) }
        heading("Быстрый пересчёт 100 единиц")
        val quick = listOf("USD", "EUR", "CNY", "GBP", "KZT", "BTC", "ETH", "USDT").filter { it in CurrencyInfo.codes }; for (cur in quick) { if (cur == state.settings.baseCurrency) continue; val cc = card(this, p); val r = row(this); r.addView(text(this, "100 $cur", 14f, p.text, true)); r.addView(spacer(this)); r.addView(text(this, money(RatesMath.convert(100.0, cur, state.settings.baseCurrency, state), state.settings.baseCurrency), 14f, p.brand, true)); cc.addView(r); content.addView(cc) }
        val manual = actionButton(this, p, "Задать ручные курсы"); manual.setOnClickListener { showManualRates() }; content.addView(manual)
    }

    private fun analyticsPage() {
        val p = pal(); val eng = engine(); heading("Аналитика", "Доходы, расходы, чистый поток, структура и крупные операции")
        val chips = row(this); listOf(3, 6, 12).forEach { m -> val b = chip(this, p, "$m мес", analyticsMonths == m); b.setOnClickListener { analyticsMonths = m; render() }; chips.addView(b) }; content.addView(chips); content.addView(vspace(this, 8))
        val toYm = Dates.nowYM(); val fromYm = Dates.addYM(toYm, -(analyticsMonths - 1).toLong()); val (from, _) = Dates.monthBounds(fromYm); val (_, to) = Dates.monthBounds(toYm); val events = eng.buildEvents(from, to)
        val fact = events.filter { it.status == "done" }; val (inc, exp, net) = eng.totals(fact); val daysCount = maxOf(1.0, (Dates.diffDays(from, to) + 1).toDouble()); val expensiveDay = events.filter { it.amount < 0 }.groupBy { it.date }.maxByOrNull { it.value.sumOf { e -> RatesMath.convert(-e.amount, e.currency, state.settings.baseCurrency, state) } }
        addTwoStats(stat("Доходы (факт)", baseMoney(inc), "за $analyticsMonths мес", p.mint), stat("Расходы (факт)", baseMoney(exp), "за $analyticsMonths мес", p.rose)); addTwoStats(stat("Накоплено", baseMoney(net), "норма сбережений ${if (inc == 0.0) "—" else Money.percent(net / inc * 100)}", if (net >= 0) p.mint else p.rose), stat("Средний расход", baseMoney(exp / daysCount * 30.4375), "в месяц по фактическим дням", p.amber)); addTwoStats(stat("Самый дорогой день", expensiveDay?.let { baseMoney(it.value.sumOf { e -> RatesMath.convert(-e.amount, e.currency, state.settings.baseCurrency, state) }) } ?: "—", expensiveDay?.key?.let { Dates.fmt(it) } ?: "", p.rose), stat("Событий", events.size.toString(), "план и факт вместе"))
        val months = (0 until analyticsMonths).map { off -> Dates.addYM(fromYm, off.toLong()) }; val incByMonth = months.map { ym -> events.filter { Dates.ymOf(it.date) == ym && it.amount > 0 }.sumOf { RatesMath.convert(it.amount, it.currency, state.settings.baseCurrency, state) } }; val expByMonth = months.map { ym -> events.filter { Dates.ymOf(it.date) == ym && it.amount < 0 }.sumOf { RatesMath.convert(-it.amount, it.currency, state.settings.baseCurrency, state) } }
        val bc = card(this, p); bc.addView(text(this, "Доходы и расходы по месяцам", 15f, p.text, true)); val bars = MonthlyBarsView(this, incByMonth, expByMonth, months.map { Dates.monthLabel(it).take(3) }, p); bars.layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(200)); bc.addView(bars); bc.addView(text(this, "Зелёное — доходы, красное — расходы", 11f, p.muted)); content.addView(bc)
        val nc = card(this, p); nc.addView(text(this, "Чистый денежный поток", 15f, p.text, true)); val netChart = LineChartView(this, months.indices.map { incByMonth[it] - expByMonth[it] }, months.map { Dates.monthLabel(it).take(3) }, p, p.mint); netChart.layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(150)); nc.addView(netChart); content.addView(nc)
        heading("Расходы по категориям"); val expCats = eng.categoryBreakdown(events, false); if (expCats.isEmpty()) empty("Нет расходов", "За выбранный период расходов нет") else expCats.take(10).forEach { (cat, value, _) -> val c = card(this, p); val r = row(this); r.addView(text(this, cat?.name ?: "Без категории", 13f, p.text, true)); r.addView(spacer(this)); r.addView(text(this, baseMoney(value), 13f, p.rose, true)); c.addView(r); c.addView(progress(this, p, if (exp == 0.0) 0.0 else value / expCats.sumOf { it.second }.coerceAtLeast(1.0), try { Color.parseColor(cat?.color ?: "#fb7185") } catch (_: Exception) { p.rose })); content.addView(c) }
        heading("Доходы по категориям"); val incCats = eng.categoryBreakdown(events, true); if (incCats.isEmpty()) empty("Нет доходов", "За выбранный период доходов нет") else incCats.take(8).forEach { (cat, value, _) -> val c = card(this, p); val r = row(this); r.addView(text(this, cat?.name ?: "Без категории", 13f, p.text, true)); r.addView(spacer(this)); r.addView(text(this, baseMoney(value), 13f, p.mint, true)); c.addView(r); content.addView(c) }
        heading("Крупные операции"); events.filter { it.amount < 0 }.sortedBy { RatesMath.convert(it.amount, it.currency, state.settings.baseCurrency, state) }.take(15).forEach { eventRow(it) }
    }

    private fun settingsPage() {
        val p = pal(); val s = state.settings
        heading("Настройки", "Базовая валюта, отображение, категории, данные и резервные копии")
        val c = card(this, p); c.addView(text(this, "Основное", 16f, p.text, true))
        c.addView(text(this, "Базовая валюта: ${s.baseCurrency} · Источник курсов: ${providerName(s.ratesProvider)} · Тема: ${s.theme} · Начало финансового месяца: ${s.monthStartDay}-го", 13f, p.muted))
        val edit = actionButton(this, p, "Изменить основные настройки", true); edit.setOnClickListener { showSettingsForm() }; c.addView(edit)
        val manual = actionButton(this, p, "Ручные курсы валют"); manual.setOnClickListener { showManualRates() }; c.addView(manual)
        val rates = actionButton(this, p, "Обновить курсы сейчас"); rates.setOnClickListener { refreshRates(false) }; c.addView(rates); content.addView(c)
        heading("Категории", "Название, тип, цвет и месячный лимит", "＋ Категория") { showCategoryForm(null) }
        for (cat in state.categories.sortedWith(compareBy<Category> { it.kind }.thenBy { it.order })) { val cc = card(this, p); val r = row(this); val dot = View(this).apply { background = rounded(try { Color.parseColor(cat.color) } catch (_: Exception) { p.brand }, 999, this@MainActivity); layoutParams = LinearLayout.LayoutParams(dp(12), dp(12)).apply { setMargins(0, 0, dp(10), 0) } }; r.addView(dot); val col = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f) }; col.addView(text(this, cat.name, 14f, p.text, true)); col.addView(text(this, "${if (cat.kind == "income") "доход" else "расход"}${cat.budgetMonthly?.let { " · лимит ${baseMoney(it)}/мес" } ?: ""} · ${cat.color}", 11f, p.muted)); r.addView(col); val e = actionButton(this, p, "Изменить"); e.setOnClickListener { showCategoryForm(cat) }; val d = actionButton(this, p, "Удалить", danger = true); d.setOnClickListener { confirm("Удалить категорию «${cat.name}»?") { state.categories.remove(cat); save() } }; r.addView(e); r.addView(d); cc.addView(r); content.addView(cc) }
        heading("Данные")
        val dc = card(this, p); dc.addView(text(this, "Данные хранятся локально в файле приложения. Экспорт JSON совместим с PWA BudgetLIFE: можно перенести данные между версиями.", 12f, p.muted))
        val export = actionButton(this, p, "Экспорт JSON", true); export.setOnClickListener { showExport() }; dc.addView(export); val import = actionButton(this, p, "Импорт JSON"); import.setOnClickListener { showImport() }; dc.addView(import); val backup = actionButton(this, p, "Создать резервную копию"); backup.setOnClickListener { store.saveBackup("Ручная ${Dates.today()}", state); toast("Резервная копия создана"); render() }; dc.addView(backup); val backups = actionButton(this, p, "Резервные копии (${store.listBackups().size})"); backups.setOnClickListener { showBackups() }; dc.addView(backups); content.addView(dc)
        heading("Приложение")
        val ac = card(this, p); val demo = actionButton(this, p, "Загрузить демо-данные"); demo.setOnClickListener { confirm("Заменить текущие данные демо-данными? Сначала будет создана резервная копия.") { store.saveBackup("Перед загрузкой демо", state); state = Demo.build(); save() } }; ac.addView(demo); val reset = actionButton(this, p, "Сбросить всё", danger = true); reset.setOnClickListener { confirm("Сбросить все данные BudgetLIFE? Сначала будет создана резервная копия.") { store.saveBackup("Перед сбросом", state); val fresh = AppState.defaults(); fresh.settings.onboarded = true; state = fresh; save() } }; ac.addView(reset); ac.addView(text(this, "BudgetLIFE Android 1.0 · Kotlin · данные совместимы с PWA JSON", 11f, p.muted)); content.addView(ac)
    }

    private inner class Form {
        val root = LinearLayout(this@MainActivity).apply { orientation = LinearLayout.VERTICAL; setPadding(dp(18), dp(8), dp(18), dp(4)) }
        fun label(s: String) { root.addView(text(this@MainActivity, s, 12f, pal().muted, true)) }
        fun edit(label: String, value: String = "", numeric: Boolean = false, multiline: Boolean = false): EditText { label(label); val e = EditText(this@MainActivity).apply { setText(value); setSingleLine(!multiline); if (numeric) inputType = InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_FLAG_DECIMAL or InputType.TYPE_NUMBER_FLAG_SIGNED; setTextColor(pal().text); setHintTextColor(pal().muted); background = rounded(pal().card2, 12, this@MainActivity, pal().line); setPadding(dp(11), dp(9), dp(11), dp(9)) }; root.addView(e); return e }
        fun spinner(label: String, options: List<String>, selected: String?): Spinner { label(label); val sp = Spinner(this@MainActivity); sp.adapter = ArrayAdapter(this@MainActivity, android.R.layout.simple_spinner_dropdown_item, options); val idx = options.indexOf(selected); if (idx >= 0) sp.setSelection(idx); sp.background = rounded(pal().card2, 12, this@MainActivity, pal().line); root.addView(sp); return sp }
        fun check(label: String, checked: Boolean): CheckBox { val cb = CheckBox(this@MainActivity).apply { text = label; isChecked = checked; setTextColor(pal().text) }; root.addView(cb); return cb }
        fun note(s: String) { root.addView(text(this@MainActivity, s, 11f, pal().muted)) }
    }
    private fun spinner(options: List<String>, selected: String?): Spinner { val sp = Spinner(this); sp.adapter = ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item, options); val i = options.indexOf(selected); if (i >= 0) sp.setSelection(i); return sp }
    private fun showForm(title: String, form: Form, saveLabel: String = "Сохранить", onSave: () -> Unit) { val scroll = ScrollView(this); scroll.addView(form.root); AlertDialog.Builder(this).setTitle(title).setView(scroll).setPositiveButton(saveLabel) { _, _ -> onSave() }.setNegativeButton("Отмена", null).show() }
    private fun confirm(title: String, action: () -> Unit) { AlertDialog.Builder(this).setTitle(title).setPositiveButton("Подтвердить") { _, _ -> action() }.setNegativeButton("Отмена", null).show() }
    private fun parseDateOr(value: String, fallback: String): String = try { LocalDate.parse(value.trim()).toString() } catch (_: Exception) { fallback }
    private fun formatRate(v: Double): String = when { v >= 100 -> String.format(Dates.RU, "%.2f", v); v >= 1 -> String.format(Dates.RU, "%.4f", v); else -> String.format(Dates.RU, "%.6f", v) }
    private fun providerName(id: String) = when (id) { "cbr" -> "ЦБ РФ"; "ecb" -> "ЕЦБ (Frankfurter)"; "erapi" -> "ExchangeRate API"; "jsdelivr" -> "Currency API (CDN)"; "manual" -> "ручные курсы"; else -> "авто" }
    private fun accountTypeLabel(type: String) = mapOf("cash" to "Наличные", "card" to "Карта", "savings" to "Накопительный счёт", "deposit" to "Вклад", "broker" to "Брокерский счёт", "crypto" to "Криптокошелёк", "credit" to "Кредитный счёт", "other" to "Другое")[type] ?: type
    private fun capitalizationLabel(v: String) = mapOf("none" to "без процентов", "daily" to "ежедневно", "monthly" to "раз в месяц", "quarterly" to "раз в квартал", "yearly" to "раз в год", "endOfTerm" to "в конце срока")[v] ?: v
    private fun creditKindLabel(v: String) = mapOf("loan" to "Кредит", "credit_card" to "Кредитная карта", "installment" to "Рассрочка")[v] ?: v

    private fun showEventDialog(e: CashEvent) {
        val p = pal(); val tx = state.transactions.firstOrNull { it.sourceKey == e.sourceKey }
        val items = mutableListOf<String>(); items += if (e.status == "done") "Снять отметку выполнения" else "Отметить выполненным"; if (tx != null) items += "Изменить операцию"; items += "Подробности"
        AlertDialog.Builder(this).setTitle(e.title).setItems(items.toTypedArray()) { _, which -> when (which) { 0 -> toggleEventDone(e); 1 -> if (tx != null) showTransactionForm(tx) else showEventDetails(e); else -> showEventDetails(e) } }.setNegativeButton("Закрыть", null).show()
    }
    private fun showEventDetails(e: CashEvent) { AlertDialog.Builder(this).setTitle(e.title).setMessage("Дата: ${Dates.fmt(e.date)}\nСумма: ${money(e.amount, e.currency, true)}\nСчёт: ${accName(e.accountId)}\nКатегория: ${catName(e.categoryId)}\nСтатус: ${if (e.status == "done") "факт" else "план"}\nИсточник: ${e.sourceType}\n${e.note ?: ""}").setPositiveButton("OK", null).show() }
    private fun toggleEventDone(e: CashEvent) {
        val existing = state.transactions.firstOrNull { it.sourceKey == e.sourceKey }
        if (existing != null) { if (existing.status == "done") { if (existing.sourceType == "manual" || existing.sourceType == "planned") existing.status = "planned" else state.transactions.remove(existing) } else { existing.status = "done"; existing.amount = e.amount; existing.date = e.date; existing.categoryId = e.categoryId ?: existing.categoryId }; existing.updatedAt = System.currentTimeMillis() }
        else state.transactions += Transaction(uid("tx"), e.date, e.amount, e.currency, e.accountId, null, e.categoryId, e.title, e.note, if (e.kind == "transfer") "transfer" else if (e.amount >= 0) "income" else "expense", "done", e.sourceType, e.sourceId, e.sourceKey)
        save(); toast(if (e.status == "done") "Отметка снята" else "Отмечено выполненным")
    }

    private fun showTransactionForm(existing: Transaction?, presetDate: String = Dates.today()) {
        if (state.accounts.isEmpty()) { toast("Сначала создайте счёт"); showAccountForm(null); return }
        val f = Form(); val isNew = existing == null; val tx = existing ?: Transaction(uid("tx"), presetDate, -1000.0, state.accounts.first().currency, state.accounts.first().id, null, null, "", null, "expense", "planned", "planned")
        val title = f.edit("Название", tx.title)
        val date = f.edit("Дата (ГГГГ-ММ-ДД)", tx.date)
        val amount = f.edit("Сумма: доход положительная, расход — с минусом", Money.input(abs(tx.amount)), numeric = true)
        val kind = f.spinner("Тип", listOf("expense", "income", "transfer"), tx.kind)
        val status = f.spinner("Статус", listOf("planned", "done"), tx.status)
        val account = f.spinner("Счёт", state.accounts.map { it.name }, accName(tx.accountId)); val toAccount = f.spinner("Счёт получателя (для перевода)", listOf("—") + state.accounts.map { it.name }, tx.toAccountId?.let { accName(it) } ?: "—")
        val cats = listOf("—") + state.categories.map { it.name }; val category = f.spinner("Категория", cats, tx.categoryId?.let { catName(it) } ?: "—")
        val currency = f.spinner("Валюта", CurrencyInfo.codes, tx.currency)
        val recurrence = f.edit("Повторение: пусто или N:day/week/month/year, например 1:month", if (tx.recurrenceEvery != null) "${tx.recurrenceEvery}:${tx.recurrenceUnit}" else "")
        val until = f.edit("Повторять до даты (необязательно)", tx.recurrenceUntil ?: "")
        val note = f.edit("Заметка", tx.note ?: "", multiline = true)
        val tags = f.edit("Теги через запятую", tx.tags.joinToString(", "))
        showForm(if (isNew) "Новая операция" else "Операция", f) {
            val selectedKind = listOf("expense", "income", "transfer")[kind.selectedItemPosition]; val raw = Money.parse(amount.text.toString()); val signed = if (selectedKind == "expense") -abs(raw) else abs(raw)
            tx.title = title.text.toString().ifBlank { "Операция" }; tx.date = parseDateOr(date.text.toString(), tx.date); tx.amount = signed; tx.kind = selectedKind; tx.status = listOf("planned", "done")[status.selectedItemPosition]; tx.accountId = state.accounts[account.selectedItemPosition].id; tx.toAccountId = if (toAccount.selectedItemPosition > 0) state.accounts[toAccount.selectedItemPosition - 1].id else null; tx.categoryId = if (category.selectedItemPosition > 0) state.categories[category.selectedItemPosition - 1].id else null; tx.currency = CurrencyInfo.codes[currency.selectedItemPosition]; tx.note = note.text.toString().ifBlank { null }; tx.tags = tags.text.toString().split(",").map { it.trim() }.filter { it.isNotBlank() }.toMutableList(); tx.updatedAt = System.currentTimeMillis(); if (tx.sourceType == "manual" && tx.status == "done") tx.sourceType = "manual"
            val rec = recurrence.text.toString().trim(); if (rec.contains(":")) { tx.recurrenceEvery = rec.substringBefore(":").toIntOrNull()?.coerceAtLeast(1); tx.recurrenceUnit = rec.substringAfter(":").ifBlank { "month" }; tx.recurrenceUntil = until.text.toString().ifBlank { null } } else { tx.recurrenceEvery = null; tx.recurrenceUnit = null; tx.recurrenceUntil = null }
            if (isNew) state.transactions += tx; save()
        }
        if (!isNew) { /* удаление доступно из списка через долгую логику формы ниже не делаем */ }
    }

    private fun showAccountForm(existing: Account?) {
        val f = Form(); val isNew = existing == null; val acc = existing ?: Account(uid("acc"), "Новый счёт", "card", state.settings.baseCurrency, 0.0, "#38c3f5", "CreditCard", null, true, false, System.currentTimeMillis())
        val name = f.edit("Название", acc.name); val type = f.spinner("Тип счёта", listOf("card", "cash", "savings", "deposit", "broker", "crypto", "credit", "other"), acc.type); val currency = f.spinner("Валюта", CurrencyInfo.codes, acc.currency); val balance = f.edit("Текущий баланс", Money.input(acc.balance), numeric = true); val creditLimit = f.edit("Кредитный лимит (для кредитного счёта)", acc.creditLimit?.let { Money.input(it) } ?: "", numeric = true); val include = f.check("Учитывать в общем балансе", acc.includeInTotal); val note = f.edit("Заметка", acc.note ?: "")
        val interest = f.check("Начисляются проценты", acc.interest.enabled); val rate = f.edit("Годовая ставка, %", Money.input(acc.interest.annualRate), numeric = true); val cap = f.spinner("Капитализация", listOf("monthly", "daily", "quarterly", "yearly", "endOfTerm", "none"), acc.interest.capitalization); val payoutDay = f.edit("День зачисления процентов", acc.interest.payoutDay?.toString() ?: "", numeric = true); val payoutMode = f.spinner("Что делать с процентами", listOf("compound", "payout"), acc.interest.payoutMode); val payoutAcc = f.spinner("Счёт выплаты процентов", listOf("—") + state.accounts.map { it.name }, acc.interest.payoutAccountId?.let { accName(it) } ?: "—"); val termEnd = f.edit("Дата окончания вклада", acc.interest.termEnd ?: "")
        val topup = f.edit("Автопополнение: сумма в месяц", Money.input(acc.interest.monthlyTopUp), numeric = true); val topupDay = f.edit("День пополнения", acc.interest.topUpDay.toString(), numeric = true); val color = f.edit("Цвет (#RRGGBB)", acc.color)
        showForm(if (isNew) "Новый счёт" else "Счёт", f) { acc.name = name.text.toString().ifBlank { acc.name }; acc.type = listOf("card", "cash", "savings", "deposit", "broker", "crypto", "credit", "other")[type.selectedItemPosition]; acc.currency = CurrencyInfo.codes[currency.selectedItemPosition]; acc.balance = Money.parse(balance.text.toString()); acc.creditLimit = creditLimit.text.toString().takeIf { it.isNotBlank() }?.let { Money.parse(it) }; acc.includeInTotal = include.isChecked; acc.note = note.text.toString().ifBlank { null }; acc.color = color.text.toString().ifBlank { acc.color }; acc.interest.enabled = interest.isChecked; acc.interest.annualRate = Money.parse(rate.text.toString()); acc.interest.capitalization = listOf("monthly", "daily", "quarterly", "yearly", "endOfTerm", "none")[cap.selectedItemPosition]; acc.interest.payoutDay = payoutDay.text.toString().toIntOrNull(); acc.interest.payoutMode = listOf("compound", "payout")[payoutMode.selectedItemPosition]; acc.interest.payoutAccountId = if (payoutAcc.selectedItemPosition > 0) state.accounts[payoutAcc.selectedItemPosition - 1].id else null; acc.interest.termEnd = termEnd.text.toString().ifBlank { null }; acc.interest.monthlyTopUp = Money.parse(topup.text.toString()); acc.interest.topUpDay = topupDay.text.toString().toIntOrNull()?.coerceIn(1, 31) ?: 5; if (isNew) { state.accounts += acc; state.settings.onboarded = true }; save() }
    }
    private fun showBalanceDialog(acc: Account) { val f = Form(); val balance = f.edit("Текущий баланс ${acc.name}", Money.input(acc.balance), numeric = true); showForm("Баланс счёта", f) { acc.balance = Money.parse(balance.text.toString()); save() } }

    private fun showIncomeForm(existing: IncomeSource?) {
        if (state.accounts.isEmpty()) { toast("Сначала создайте счёт"); return }
        val f = Form(); val isNew = existing == null; val src = existing ?: IncomeSource(uid("inc"), "Новый доход", "salary", state.accounts.first().id, state.settings.baseCurrency, 0.0, false, mutableListOf(PayDay(uid("pd"), "Выплата", 10, 1.0, null, "prevWorkday")), Dates.nowYM(), null, null, null, true, false, 0.0, mutableMapOf(), state.incomes.size)
        val name = f.edit("Название", src.name); val amount = f.edit("Сумма за месяц (до налога)", Money.input(src.amount), numeric = true); val account = f.spinner("Счёт", state.accounts.map { it.name }, accName(src.accountId)); val currency = f.spinner("Валюта", CurrencyInfo.codes, src.currency); val kind = f.spinner("Тип", listOf("salary", "advance", "freelance", "rental", "dividends", "social", "other"), src.kind); val variable = f.check("Сумма меняется от месяца к месяцу (сдельная работа)", src.variable); val tax = f.check("Удерживать налог", src.taxEnabled); val taxRate = f.edit("Ставка налога, %", Money.input(src.taxRate), numeric = true); val start = f.edit("Месяц начала (ГГГГ-ММ)", src.startYM); val end = f.edit("Месяц окончания (необязательно)", src.endYM ?: "")
        val paydays = f.edit("Дни выплат: по одному на строку «Название | день | доля% или сумма | exact/prevWorkday/nextWorkday». День -1 — последний, -2 — предпоследний", src.payDays.joinToString("\n") { "${it.label} | ${it.day} | ${it.amount?.let { a -> Money.input(a) } ?: ((it.share ?: 1.0) * 100).toInt().toString() + "%"} | ${it.rule}" }, multiline = true)
        val active = f.check("Активен", src.active); val note = f.edit("Заметка", src.note ?: "")
        showForm(if (isNew) "Новый доход" else "Доход", f) { src.name = name.text.toString().ifBlank { src.name }; src.amount = Money.parse(amount.text.toString()); src.accountId = state.accounts[account.selectedItemPosition].id; src.currency = CurrencyInfo.codes[currency.selectedItemPosition]; src.kind = listOf("salary", "advance", "freelance", "rental", "dividends", "social", "other")[kind.selectedItemPosition]; src.variable = variable.isChecked; src.taxEnabled = tax.isChecked; src.taxRate = Money.parse(taxRate.text.toString()); src.startYM = start.text.toString().takeIf { it.matches(Regex("\\d{4}-\\d{2}")) } ?: src.startYM; src.endYM = end.text.toString().ifBlank { null }; src.active = active.isChecked; src.note = note.text.toString().ifBlank { null }; val parsed = paydays.text.toString().lines().mapNotNull { line -> val parts = line.split("|").map { it.trim() }; if (parts.size < 2) null else { val raw = parts.getOrNull(2) ?: "100%"; val isPercent = raw.endsWith("%"); PayDay(uid("pd"), parts[0].ifBlank { "Выплата" }, parts[1].toIntOrNull() ?: 10, if (isPercent) Money.parse(raw.removeSuffix("%")) / 100.0 else null, if (isPercent) null else Money.parse(raw), parts.getOrNull(3) ?: "prevWorkday") } }; if (parsed.isNotEmpty()) src.payDays = parsed.toMutableList(); if (isNew) state.incomes += src; save() }
    }
    private fun showIncomeMonths(src: IncomeSource) {
        val items = (0..11).map { off -> val ym = Dates.addYM(Dates.nowYM(), off.toLong()); val total = engine().incomeMonthPayments(src, ym).sumOf { it.third }; "${Dates.monthLabel(ym)} — ${money(total, src.currency)}${src.overrides[ym]?.let { " · изменено" } ?: ""}" }.toTypedArray()
        AlertDialog.Builder(this).setTitle("${src.name}: по месяцам").setItems(items) { _, which -> val ym = Dates.addYM(Dates.nowYM(), which.toLong()); showIncomeMonthOverride(src, ym) }.setNegativeButton("Закрыть", null).show()
    }
    private fun showIncomeMonthOverride(src: IncomeSource, ym: String) {
        val f = Form(); val ov = src.overrides[ym] ?: MonthOverride(); val amount = f.edit("Сумма за месяц (пусто — базовая)", ov.amount?.let { Money.input(it) } ?: "", numeric = true); val skip = f.check("Дохода в этом месяце нет", ov.skip); val note = f.edit("Заметка месяца", ov.note ?: ""); f.note("Конкретные выплаты: по одной на строку «ID выплаты | дата | сумма | skip». ID видны в форме дохода по порядку: ${src.payDays.mapIndexed { i, pd -> "${i + 1}:${pd.label}" }.joinToString(", ")}")
        val lines = f.edit("Выплаты месяца", ov.payDays.joinToString("\n") { "${src.payDays.indexOfFirst { pd -> pd.id == it.id } + 1} | ${it.date ?: ""} | ${it.amount?.let { a -> Money.input(a) } ?: ""} | ${if (it.skipped) "skip" else ""}" }, multiline = true)
        showForm("${src.name} · ${Dates.monthLabel(ym)}", f) { val newOv = MonthOverride(Money.parse(amount.text.toString()).takeIf { amount.text.toString().isNotBlank() }, mutableListOf(), skip.isChecked, note.text.toString().ifBlank { null }); lines.text.toString().lines().forEach { line -> val parts = line.split("|").map { it.trim() }; val idx = parts.getOrNull(0)?.toIntOrNull()?.minus(1) ?: return@forEach; val pd = src.payDays.getOrNull(idx) ?: return@forEach; newOv.payDays += PayDayOverride(pd.id, parts.getOrNull(1)?.ifBlank { null }, parts.getOrNull(2)?.takeIf { it.isNotBlank() }?.let { Money.parse(it) }, parts.getOrNull(3) == "skip") }; if (newOv.amount == null && !newOv.skip && newOv.payDays.isEmpty() && newOv.note == null) src.overrides.remove(ym) else src.overrides[ym] = newOv; save() }
    }

    private fun showSubscriptionForm(existing: Subscription?) {
        if (state.accounts.isEmpty()) { toast("Сначала создайте счёт"); return }
        val f = Form(); val isNew = existing == null; val sub = existing ?: Subscription(uid("sub"), "Новая подписка", 0.0, state.settings.baseCurrency, 1, "month", Dates.today(), null, null, state.accounts.first().id, true, true, 1, null, null, mutableListOf(), "#8b5cf6", "Repeat")
        val name = f.edit("Название", sub.name); val amount = f.edit("Сумма", Money.input(sub.amount), numeric = true); val currency = f.spinner("Валюта", CurrencyInfo.codes, sub.currency); val every = f.edit("Цикл: каждые N", sub.every.toString(), numeric = true); val unit = f.spinner("Единица цикла", listOf("month", "day", "week", "year"), sub.unit); val start = f.edit("Дата первого списания", sub.startDate); val end = f.edit("Дата окончания (необязательно)", sub.endDate ?: ""); val account = f.spinner("Счёт", state.accounts.map { it.name }, accName(sub.accountId)); val cat = f.spinner("Категория", listOf("—") + state.categories.filter { it.kind == "expense" }.map { it.name }, sub.categoryId?.let { catName(it) } ?: "—"); val trial = f.edit("Бесплатный период до даты", sub.trialUntil ?: ""); val remind = f.edit("Напомнить за дней", sub.remindDays.toString(), numeric = true); val active = f.check("Активна", sub.active); val renew = f.check("Автопродление", sub.autoRenew); val note = f.edit("Заметка", sub.note ?: "")
        showForm(if (isNew) "Новая подписка" else "Подписка", f) { val oldAmount = sub.amount; sub.name = name.text.toString().ifBlank { sub.name }; sub.amount = Money.parse(amount.text.toString()); sub.currency = CurrencyInfo.codes[currency.selectedItemPosition]; sub.every = every.text.toString().toIntOrNull()?.coerceAtLeast(1) ?: 1; sub.unit = listOf("month", "day", "week", "year")[unit.selectedItemPosition]; sub.startDate = parseDateOr(start.text.toString(), sub.startDate); sub.endDate = end.text.toString().ifBlank { null }; sub.accountId = state.accounts[account.selectedItemPosition].id; val cats = state.categories.filter { it.kind == "expense" }; sub.categoryId = if (cat.selectedItemPosition > 0) cats[cat.selectedItemPosition - 1].id else null; sub.trialUntil = trial.text.toString().ifBlank { null }; sub.remindDays = remind.text.toString().toIntOrNull() ?: 1; sub.active = active.isChecked; sub.autoRenew = renew.isChecked; sub.note = note.text.toString().ifBlank { null }; if (!isNew && oldAmount != sub.amount) sub.priceHistory += Dates.today() to sub.amount; if (isNew) state.subscriptions += sub; save() }
    }

    private fun showCreditForm(existing: Credit?) {
        if (state.accounts.isEmpty()) { toast("Сначала создайте счёт"); return }
        val f = Form(); val isNew = existing == null; val cr = existing ?: Credit(uid("cr"), "Новый кредит", "loan", state.accounts.first().id, state.settings.baseCurrency, 0.0, 0.0, 12, Dates.today(), 15, "annuity", null, null, null, null, null, null, null, null, "min", null, 0.0, null, "#f43f5e", true)
        val name = f.edit("Название", cr.name); val kind = f.spinner("Тип", listOf("loan", "installment", "credit_card"), cr.kind); val account = f.spinner("Счёт списания", state.accounts.map { it.name }, accName(cr.accountId)); val currency = f.spinner("Валюта", CurrencyInfo.codes, cr.currency)
        val principal = f.edit("Сумма кредита / лимит карты", Money.input(if (cr.kind == "credit_card") (cr.limit ?: 0.0) else cr.principal), numeric = true); val balance = f.edit("Текущий остаток долга (необязательно)", cr.currentBalance?.let { Money.input(it) } ?: "", numeric = true); val used = f.edit("Задолженность по карте", cr.used?.let { Money.input(it) } ?: "", numeric = true); val rate = f.edit("Годовая ставка, %", Money.input(cr.annualRate), numeric = true); val term = f.edit("Срок, месяцев", cr.termMonths.toString(), numeric = true); val start = f.edit("Дата выдачи", cr.startDate); val payDay = f.edit("День платежа", cr.paymentDay.toString(), numeric = true); val ptype = f.spinner("Тип платежа", listOf("annuity", "differentiated"), cr.paymentType)
        val grace = f.edit("Беспроцентный период, дней (карта)", cr.graceDays?.toString() ?: "", numeric = true); val statement = f.edit("День выписки (карта)", cr.statementDay?.toString() ?: "", numeric = true); val graceDay = f.edit("Крайний день платежа (карта)", cr.gracePaymentDay?.toString() ?: "", numeric = true); val minPct = f.edit("Минимальный платёж, %", cr.minPaymentPercent?.let { Money.input(it) } ?: "5", numeric = true); val repay = f.spinner("Стратегия погашения карты", listOf("full", "min", "custom"), cr.repayMode); val custom = f.edit("Своя сумма погашения", cr.customRepayAmount?.let { Money.input(it) } ?: "", numeric = true); val extra = f.edit("Досрочное погашение в месяц", Money.input(cr.extraPayment), numeric = true); val active = f.check("Активен", cr.active); val note = f.edit("Заметка", cr.note ?: "")
        showForm(if (isNew) "Новый кредит" else "Кредит", f) { cr.name = name.text.toString().ifBlank { cr.name }; cr.kind = listOf("loan", "installment", "credit_card")[kind.selectedItemPosition]; cr.accountId = state.accounts[account.selectedItemPosition].id; cr.currency = CurrencyInfo.codes[currency.selectedItemPosition]; val amount = Money.parse(principal.text.toString()); if (cr.kind == "credit_card") cr.limit = amount else cr.principal = amount; cr.currentBalance = balance.text.toString().takeIf { it.isNotBlank() }?.let { Money.parse(it) }; cr.used = used.text.toString().takeIf { it.isNotBlank() }?.let { Money.parse(it) }; cr.annualRate = Money.parse(rate.text.toString()); cr.termMonths = term.text.toString().toIntOrNull() ?: 12; cr.startDate = parseDateOr(start.text.toString(), cr.startDate); cr.paymentDay = payDay.text.toString().toIntOrNull()?.coerceIn(1, 31) ?: 15; cr.paymentType = listOf("annuity", "differentiated")[ptype.selectedItemPosition]; cr.graceDays = grace.text.toString().toIntOrNull(); cr.statementDay = statement.text.toString().toIntOrNull(); cr.gracePaymentDay = graceDay.text.toString().toIntOrNull(); cr.minPaymentPercent = Money.parse(minPct.text.toString()); cr.repayMode = listOf("full", "min", "custom")[repay.selectedItemPosition]; cr.customRepayAmount = custom.text.toString().takeIf { it.isNotBlank() }?.let { Money.parse(it) }; cr.extraPayment = Money.parse(extra.text.toString()); cr.active = active.isChecked; cr.note = note.text.toString().ifBlank { null }; if (isNew) state.credits += cr; save() }
    }

    private fun showTransferForm() {
        if (state.accounts.size < 2) { toast("Нужно минимум два счёта"); return }
        val f = Form(); val from = f.spinner("Откуда", state.accounts.map { it.name }, state.accounts.first().name); val to = f.spinner("Куда", state.accounts.map { it.name }, state.accounts.getOrNull(1)?.name); val amount = f.edit("Сумма", "", numeric = true); val date = f.edit("Дата", Dates.today()); val status = f.spinner("Статус", listOf("done", "planned"), "done")
        showForm("Перевод между счетами", f) { val fromAcc = state.accounts[from.selectedItemPosition]; val toAcc = state.accounts[to.selectedItemPosition]; if (fromAcc.id == toAcc.id) { toast("Выберите разные счета"); return@showForm }; val v = abs(Money.parse(amount.text.toString())); state.transactions += Transaction(uid("tx"), parseDateOr(date.text.toString(), Dates.today()), -v, fromAcc.currency, fromAcc.id, toAcc.id, null, "Перевод: ${fromAcc.name} → ${toAcc.name}", null, "transfer", listOf("done", "planned")[status.selectedItemPosition], "manual"); save() }
    }

    private fun showCategoryForm(existing: Category?) {
        val f = Form(); val isNew = existing == null; val cat = existing ?: Category(uid("cat"), "Новая категория", "expense", "#38c3f5", "Circle", null, state.categories.size)
        val name = f.edit("Название", cat.name); val kind = f.spinner("Тип", listOf("expense", "income"), cat.kind); val color = f.edit("Цвет (#RRGGBB)", cat.color); val limit = f.edit("Месячный лимит (для расходов)", cat.budgetMonthly?.let { Money.input(it) } ?: "", numeric = true); val icon = f.edit("Иконка (имя как в PWA)", cat.icon)
        showForm(if (isNew) "Новая категория" else "Категория", f) { cat.name = name.text.toString().ifBlank { cat.name }; cat.kind = listOf("expense", "income")[kind.selectedItemPosition]; cat.color = color.text.toString().ifBlank { cat.color }; cat.budgetMonthly = limit.text.toString().takeIf { it.isNotBlank() }?.let { Money.parse(it) }; cat.icon = icon.text.toString().ifBlank { "Circle" }; if (isNew) state.categories += cat; save() }
    }

    private fun showSettingsForm() {
        val f = Form(); val s = state.settings; val base = f.spinner("Базовая валюта", CurrencyInfo.codes, s.baseCurrency); val provider = f.spinner("Источник курсов", listOf("auto", "cbr", "ecb", "erapi", "manual"), s.ratesProvider); val theme = f.spinner("Тема", listOf("dark", "light", "system"), s.theme); val hide = f.check("Скрывать суммы", s.hideBalances); val cents = f.check("Показывать копейки", s.showCents); val monthStart = f.edit("День начала финансового месяца", s.monthStartDay.toString(), numeric = true); val firstDay = f.spinner("Первый день недели", listOf("1", "0", "7"), s.firstDayOfWeek.toString()); val workweek = f.check("Календарь только по рабочим дням (настройка PWA)", s.workweekOnly)
        showForm("Основные настройки", f) { s.baseCurrency = CurrencyInfo.codes[base.selectedItemPosition]; s.ratesProvider = listOf("auto", "cbr", "ecb", "erapi", "manual")[provider.selectedItemPosition]; s.theme = listOf("dark", "light", "system")[theme.selectedItemPosition]; if (s.theme == "system") s.theme = "dark"; s.hideBalances = hide.isChecked; s.showCents = cents.isChecked; s.monthStartDay = monthStart.text.toString().toIntOrNull()?.coerceIn(1, 31) ?: 1; s.firstDayOfWeek = listOf(1, 0, 7)[firstDay.selectedItemPosition]; s.workweekOnly = workweek.isChecked; save(); if (s.ratesProvider != "manual") refreshRates(true) }
    }

    private fun showManualRates() {
        val f = Form(); val fields = linkedMapOf<String, EditText>(); for (cur in CurrencyInfo.codes) { if (cur == state.settings.baseCurrency) continue; fields[cur] = f.edit("1 ${state.settings.baseCurrency} = X $cur", state.settings.manualRates[cur]?.let { Money.input(it) } ?: "", numeric = true) }
        showForm("Ручные курсы", f) { state.settings.manualRates.clear(); fields.forEach { (cur, e) -> val v = Money.parse(e.text.toString()); if (v > 0) state.settings.manualRates[cur] = v }; save(); toast("Ручные курсы сохранены") }
    }

    private fun showExport() {
        val json = state.toJson().toString(2); val edit = EditText(this).apply { setText(json); setTextIsSelectable(true); minLines = 12 }
        AlertDialog.Builder(this).setTitle("Экспорт JSON").setView(edit).setPositiveButton("Копировать") { _, _ -> val cm = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager; cm.setPrimaryClip(ClipData.newPlainText("BudgetLIFE", json)); toast("JSON скопирован") }.setNeutralButton("Поделиться") { _, _ -> val intent = Intent(Intent.ACTION_SEND).apply { type = "application/json"; putExtra(Intent.EXTRA_TEXT, json); putExtra(Intent.EXTRA_SUBJECT, "BudgetLIFE export") }; startActivity(Intent.createChooser(intent, "Экспорт BudgetLIFE")) }.setNegativeButton("Закрыть", null).show()
    }
    private fun showImport() {
        val edit = EditText(this).apply { hint = "Вставьте JSON из PWA или Android BudgetLIFE"; minLines = 10 }
        AlertDialog.Builder(this).setTitle("Импорт JSON").setView(edit).setPositiveButton("Импортировать") { _, _ -> try { val parsed = JSONObject(edit.text.toString()); if (!parsed.has("accounts")) throw IllegalArgumentException("Нет accounts"); store.saveBackup("Перед импортом", state); state = AppState.fromJson(parsed); save(); toast("Импорт выполнен") } catch (e: Exception) { toast("Ошибка импорта: ${e.message}") } }.setNegativeButton("Отмена", null).show()
    }
    private fun showBackups() {
        val backups = store.listBackups(); if (backups.isEmpty()) { toast("Резервных копий пока нет"); return }
        val labels = backups.map { "${it.third} · ${java.text.SimpleDateFormat("dd.MM.yyyy HH:mm", Dates.RU).format(java.util.Date(it.second))}" }.toTypedArray()
        AlertDialog.Builder(this).setTitle("Резервные копии").setItems(labels) { _, which -> val index = backups[which].first.toInt(); AlertDialog.Builder(this).setTitle(labels[which]).setItems(arrayOf("Восстановить", "Удалить")) { _, action -> if (action == 0) { store.restoreBackup(index)?.let { restored -> store.saveBackup("Перед восстановлением", state); state = restored; save(); toast("Копия восстановлена") } } else { store.deleteBackup(index); render() } }.setNegativeButton("Отмена", null).show() }.setNegativeButton("Закрыть", null).show()
    }

    private fun refreshRates(silent: Boolean) {
        if (!silent) toast("Обновляю курсы…")
        RatesApi.refreshAsync(state) { snap, error -> runOnUiThread { if (snap != null) { state.rates = snap; store.saveRatesHistory(snap); store.save(state); if (!silent) toast("Курсы обновлены: ${providerName(snap.provider)}") } else if (!silent || state.rates == null) toast(error ?: "Не удалось получить курсы"); render() } }
    }
}
