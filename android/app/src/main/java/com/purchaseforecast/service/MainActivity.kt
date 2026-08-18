package com.purchaseforecast.service

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import java.time.LocalDate

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            PurchaseForecastApp()
        }
    }
}

@Composable
fun PurchaseForecastApp() {
    MaterialTheme {
        Surface(
            modifier = Modifier
                .fillMaxSize()
                .background(AppColors.Background),
            color = AppColors.Background,
        ) {
            DashboardScreen(state = DemoDashboard.state)
        }
    }
}

@Composable
fun DashboardScreen(state: DashboardState) {
    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = 20.dp, vertical = 24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            Text(
                text = "Purchase Forecast",
                style = MaterialTheme.typography.headlineMedium,
                fontWeight = FontWeight.SemiBold,
                color = AppColors.Ink,
            )
            Text(
                text = "Ближайшие закупки, бюджет и профиль тела",
                style = MaterialTheme.typography.bodyMedium,
                color = AppColors.Muted,
            )
        }

        item {
            SummaryBand(state = state)
        }

        item {
            SectionTitle("Ближайшие закупки")
        }

        items(state.purchaseEvents) { event ->
            PurchaseEventRow(event)
        }

        item {
            SectionTitle("Профиль тела")
            BodyProfilePanel(state.body)
        }

        item {
            SectionTitle("Что добавить дальше")
            NextStepsPanel(state.gaps)
        }
    }
}

@Composable
private fun SummaryBand(state: DashboardState) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        MetricCard(
            modifier = Modifier.weight(1f),
            label = "30 дней",
            value = "${state.totalBudgetRub} ₽",
        )
        MetricCard(
            modifier = Modifier.weight(1f),
            label = "Еда",
            value = "${state.foodBudgetRub} ₽",
        )
        MetricCard(
            modifier = Modifier.weight(1f),
            label = "Питомец",
            value = "${state.petBudgetRub} ₽",
        )
    }
}

@Composable
private fun MetricCard(modifier: Modifier = Modifier, label: String, value: String) {
    Card(
        modifier = modifier,
        colors = CardDefaults.cardColors(containerColor = AppColors.Panel),
        elevation = CardDefaults.cardElevation(defaultElevation = 0.dp),
    ) {
        Column(modifier = Modifier.padding(12.dp)) {
            Text(text = label, style = MaterialTheme.typography.labelMedium, color = AppColors.Muted)
            Spacer(modifier = Modifier.height(4.dp))
            Text(text = value, style = MaterialTheme.typography.titleMedium, color = AppColors.Ink)
        }
    }
}

@Composable
private fun PurchaseEventRow(event: PurchaseEventUi) {
    Card(
        colors = CardDefaults.cardColors(containerColor = Color.White),
        elevation = CardDefaults.cardElevation(defaultElevation = 0.dp),
    ) {
        Column(modifier = Modifier.padding(14.dp)) {
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text(text = event.name, style = MaterialTheme.typography.titleMedium, color = AppColors.Ink)
                Text(text = event.date, style = MaterialTheme.typography.bodyMedium, color = AppColors.Muted)
            }
            Spacer(modifier = Modifier.height(6.dp))
            Text(
                text = "${event.category} · ${event.quantity} · ${event.priceRub} ₽",
                style = MaterialTheme.typography.bodyMedium,
                color = AppColors.Muted,
            )
        }
    }
}

@Composable
private fun BodyProfilePanel(body: BodyProfileUi) {
    Card(
        colors = CardDefaults.cardColors(containerColor = Color.White),
        elevation = CardDefaults.cardElevation(defaultElevation = 0.dp),
    ) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(text = "Baseline: ${body.heightCm} см, ${body.weightKg} кг, BMI ${body.bmi}")
            HorizontalDivider(color = AppColors.Line)
            Text(text = "Цель: ${body.targetWeightRangeKg} кг и талия меньше ${body.maxWaistCm} см")
            Text(
                text = "Нужно заменить baseline твоими фактическими данными.",
                style = MaterialTheme.typography.bodySmall,
                color = AppColors.Muted,
            )
        }
    }
}

@Composable
private fun NextStepsPanel(gaps: List<String>) {
    Card(
        colors = CardDefaults.cardColors(containerColor = Color.White),
        elevation = CardDefaults.cardElevation(defaultElevation = 0.dp),
    ) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            gaps.forEach { gap ->
                Text(text = "• $gap", style = MaterialTheme.typography.bodyMedium, color = AppColors.Ink)
            }
        }
    }
}

@Composable
private fun SectionTitle(title: String) {
    Text(
        text = title,
        modifier = Modifier.padding(top = 8.dp),
        style = MaterialTheme.typography.titleMedium,
        fontWeight = FontWeight.SemiBold,
        color = AppColors.Ink,
    )
}

data class DashboardState(
    val totalBudgetRub: Int,
    val foodBudgetRub: Int,
    val petBudgetRub: Int,
    val purchaseEvents: List<PurchaseEventUi>,
    val body: BodyProfileUi,
    val gaps: List<String>,
)

data class PurchaseEventUi(
    val date: String,
    val category: String,
    val name: String,
    val quantity: String,
    val priceRub: Int,
)

data class BodyProfileUi(
    val heightCm: String,
    val weightKg: String,
    val bmi: String,
    val targetWeightRangeKg: String,
    val maxWaistCm: String,
)

private object DemoDashboard {
    val state = DashboardState(
        totalBudgetRub = 9670,
        foodBudgetRub = 4620,
        petBudgetRub = 4050,
        purchaseEvents = listOf(
            PurchaseEventUi(LocalDate.of(2026, 6, 18).toString(), "food", "chicken breast", "900 g", 420),
            PurchaseEventUi(LocalDate.of(2026, 6, 18).toString(), "pet", "cat food", "1500 g", 1600),
            PurchaseEventUi(LocalDate.of(2026, 6, 18).toString(), "pet", "cat litter", "10 l", 850),
            PurchaseEventUi(LocalDate.of(2026, 6, 21).toString(), "food", "chicken breast", "900 g", 420),
        ),
        body = BodyProfileUi(
            heightCm = "176.4",
            weightKg = "80.3",
            bmi = "25.8",
            targetWeightRangeKg = "68.5-74.7",
            maxWaistCm = "88.2",
        ),
        gaps = listOf(
            "импорт реальных расходов из CSV",
            "остатки дома и сроки годности",
            "профиль питания и ограничения",
            "профиль питомца с нормой корма",
        ),
    )
}

private object AppColors {
    val Background = Color(0xFFF7F4EF)
    val Panel = Color(0xFFEAF0ED)
    val Ink = Color(0xFF1F2523)
    val Muted = Color(0xFF68736F)
    val Line = Color(0xFFE0DDD6)
}

@Preview(showBackground = true)
@Composable
private fun DashboardPreview() {
    PurchaseForecastApp()
}
