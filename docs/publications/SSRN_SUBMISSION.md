# Подача рабочей статьи в SSRN

Пакет подготовлен 24 октября 2026 года для программной версии 0.1.3. В SSRN ничего не отправлено. Для подачи используйте [английский PDF](Infra_Cashflow_SSRN_Dmitry_Kazakov.pdf). [Русский PDF](Infra_Cashflow_SSRN_Dmitry_Kazakov_RU.pdf) является сопроводительной версией для читателей.

С 1 декабря 2025 года SSRN принимает новые материалы только на английском языке, включая полный текст. Английской аннотации при русском PDF недостаточно. [Официальное правило о языке](https://www.elsevier.support/ssrn/answer/does-ssrn-accept-nonenglish-submissions).

## Порядок подачи

1. Просмотрите окончательный английский PDF. Проверьте название, автора, таблицы, подписи к графикам, источники и описание ограничений. Текст должен выделяться и копироваться; PDF должен открываться без пароля, со встроенными шрифтами и без ограничений копирования. [Требования к PDF](https://www.elsevier.support/ssrn/answer/pdf-issues).
2. Уточните текущую аффилиацию автора и укажите её одинаково в PDF и профиле SSRN. Сейчас она оставлена незаполненной: организация не была подтверждена. Актуальная справка SSRN требует подтверждённую институциональную аффилиацию. Имя и email для остальных полей приведены ниже. [Аффилиация](https://www.elsevier.support/ssrn/answer/affiliation).
3. Войдите в свой аккаунт SSRN, начните новую подачу и загрузите английский PDF. Для этой работы подходят Content Format: Paper и Content Type: Preprint. Сверьте извлечённые из PDF данные с полями ниже. Если интерфейс изменился, ориентируйтесь на названия полей, а не на прежнее расположение элементов. [Общие требования](https://www.elsevier.support/ssrn/answer/get-started).
4. Добавьте ключевые слова по отдельности. Выберите одну основную предметную классификацию и при необходимости несколько дополнительных, соответствующих прогнозированию, проектному финансированию, финансовому риску и вычислительным методам. SSRN допускает от одной до семи классификаций. JEL-коды необязательны. [Классификация](https://www.elsevier.support/ssrn/answer/classification-distribution).
5. Поместите приведённую ниже декларацию использования генеративных средств вместе с аннотацией в форме. Та же декларация уже включена в рукопись и должна остаться в PDF. Сведения о финансировании и конфликтах интересов уточняются автором при подаче; пустые поля в JSON не означают, что финансирование или конфликты отсутствуют. Для немедицинской работы эти заявления рекомендуются руководством SSRN. [Политика использования инструментов](https://www.elsevier.support/ssrn/answer/AI) и [руководство к форме](https://supportcontent.elsevier.com/Support%20Hub/SSRN/SSRN_NewSubmissionForm.pdf).
6. Перед отправкой подтвердите окончательный текст, состав авторов и права на размещение. Проверьте, что версия PDF совпадает с метаданными. После отправки сохраните номер подачи. Публичную ссылку и DOI добавляйте в репозиторий только после их фактического появления.

SSRN проверяет материалы перед размещением. Подготовленный пакет не является подтверждением принятия или научного рецензирования.

## Поля для копирования

Ниже title и subtitle приведены отдельно, как в английской рукописи. Поле `title` в [submission_metadata.json](submission_metadata.json) дословно совпадает с основной строкой названия, поле `subtitle` с подзаголовком. Для поля названия в SSRN используйте основное название. Подзаголовок остаётся отдельной строкой в PDF. Аннотация и декларация ниже воспроизведены дословно из [ssrn_paper.md](ssrn_paper.md). При правке синхронно обновляйте рукопись, PDF и эти поля.

### Title

Infrastructure Cash Flow Forecasting with a Bounded Agent Harness

### Subtitle

Evidence from a Synthetic Benchmark and Software Verification

### Author

Dmitry Kazakov

### Email

dmkkazakov@gmail.com

### Affiliation

Уточняется автором при подаче. В JSON: `null`.

### Date paper was written

2026-10-24

### Content format and type

- Content Format: Paper.
- Content Type: Preprint.
- Language: English.
- Software version: 0.1.3.

### Abstract

Infrastructure cash-flow forecasting combines uncertain project performance with contractual financing limits and operational software risks. This paper separates three questions: whether the cash-and-debt ledger is correct, whether an adaptive correction improves the plan, and whether a bounded agent harness preserves valid results through incomplete actions and failed runs. Twelve seeded realisations of three synthetic regimes provide 840 rolling forecast origins and 2,520 origin-target pairs over one- to three-month horizons. For cash flow before financing, the corrected plan achieves mean absolute error of RUB 10.29 million, against RUB 20.68 million for the unchanged plan. Correction improves eight realisations but worsens all four cases with no systematic component bias. A separate scenario calculation produces a peak funding gap of RUB 376.23 million despite positive terminal cash. Verification of software version 0.1.3 includes 96 tests, a separate Decimal recalculation and 200 random configurations. Failure analysis identifies premature completion markers, state retained across retries, mutable configuration aliases, invalid cache reuse and numerical boundary errors. A five-request scripted HTTP test checks rejection of premature finalisation and subsequent completion. No live language-model planner or real-project forecast performance is evaluated. The contribution is reproducible evidence about the estimator and the execution conditions required to retain reviewable financial results, including negative findings.

### Keywords

- infrastructure finance
- cash-flow forecasting
- project finance
- agent harness
- software verification
- scenario analysis
- time-series evaluation

### JEL codes

C53; C63; G32

### Generative AI assistance

OpenAI GPT-6 Astra Pro assisted with literature discovery, software implementation, test development, computational verification support, drafting, editing and translation. Its contribution was substantial. Reported numerical results come from the executable synthetic experiment and the specified arithmetic checks, not from free-form language-model forecasts. The author is responsible for the final manuscript, interpretations and submission. No claim is made that the forecast benchmark evaluated a live language-model planner.

### Funding

Уточняется автором при подаче. В JSON: `null`. Это не утверждение об отсутствии финансирования.

### Conflicts of interest

Уточняется автором при подаче. В JSON: `null`. Это не утверждение об отсутствии конфликтов интересов.

## Согласованность версий

- Основная английская рукопись: [ssrn_paper.md](ssrn_paper.md).
- Русская сопроводительная версия: [ssrn_paper_ru.md](ssrn_paper_ru.md).
- Название, аннотация и декларация: [submission_metadata.json](submission_metadata.json).
- Данные и проверка версии: [VERIFICATION.md](../VERIFICATION.md).
- Код, к которому относятся проверки: [снимок 0.1.3](https://github.com/dmkkazakov/-infra-cashflow-agent/tree/2fa489170fb4e0700069e6369e80853d221c7cfe).

Не заменяйте происхождение эталонных файлов версии 0.1.1 на 0.1.3: в статье описана их повторная проверка текущим кодом. Прогнозный benchmark выполнен на синтетических данных. Оценки точности на реальных проектах и работы живого LLM-планировщика в статье не заявляются.
