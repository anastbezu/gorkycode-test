// app.js — основной контроллер интерфейса

import {
  sendChatMessage,
  fetchCalendarItems,
  getStoredLLMConfig,
  saveStoredLLMConfig
} from './api.js';

import {
  getBrowserTimezone,
  formatRecordDate,
  formatDateWords,
  getDateParts,
  parseIsoDate,
  formatTime
} from './dates.js';

const STORAGE_KEY_MESSAGES = 'gorky_chat_messages';

// Состояние приложения
const state = {
  messages: [],
  calendarItems: [],
  selectedDayIndex: 0, // 0 = Сегодня, 1 = Завтра ... 6
  isThinking: false,
  lastFailedText: null
};

// DOM-элементы
const chatMessagesEl = document.getElementById('chat-messages');
const emptyChatEl = document.getElementById('empty-chat');
const chatFormEl = document.getElementById('chat-form');
const chatInputEl = document.getElementById('chat-input');
const btnSendEl = document.getElementById('btn-send');
const thinkingIndicatorEl = document.getElementById('thinking-indicator');
const errorBannerEl = document.getElementById('error-banner');
const errorMessageEl = document.getElementById('error-message');
const btnRetryEl = document.getElementById('btn-retry-message');

const daysStripEl = document.getElementById('days-strip');
const tasksListEl = document.getElementById('tasks-list');
const undatedSectionEl = document.getElementById('undated-section');
const undatedListEl = document.getElementById('undated-list');
const sidebarBadgeEl = document.getElementById('sidebar-badge');

const mobileToggleBtn = document.getElementById('mobile-sidebar-toggle');
const sidebarEl = document.getElementById('sidebar-tasks');
const btnCloseSidebarEl = document.getElementById('btn-sidebar-close');
const backdropEl = document.getElementById('sidebar-backdrop');

const settingsModalEl = document.getElementById('settings-modal');
const btnOpenSettingsEl = document.getElementById('btn-settings-open');
const btnCloseSettingsEl = document.getElementById('btn-settings-close');
const btnCancelSettingsEl = document.getElementById('btn-settings-cancel');
const btnSaveSettingsEl = document.getElementById('btn-settings-save');
const inputBaseUrl = document.getElementById('input-base-url');
const inputModel = document.getElementById('input-model');
const inputApiKey = document.getElementById('input-api-key');

// Инициализация при загрузке
function initApp() {
  initChatHistory();
  initDaysStrip();
  initEventListeners();
  loadCalendar();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initApp);
} else {
  initApp();
}

function initChatHistory() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY_MESSAGES);
    if (saved) {
      state.messages = JSON.parse(saved);
    }
  } catch (e) {
    state.messages = [];
  }

  if (state.messages.length > 0) {
    emptyChatEl.classList.add('hidden');
    state.messages.forEach(msg => renderMessageRow(msg));
    scrollToBottom();
  }
}

function saveChatHistory() {
  try {
    localStorage.setItem(STORAGE_KEY_MESSAGES, JSON.stringify(state.messages));
  } catch (e) {}
}

/**
 * Генерация 7 вкладок дней (Сегодня, Завтра, ...)
 */
function initDaysStrip() {
  daysStripEl.innerHTML = '';
  const now = new Date();
  const tz = getBrowserTimezone();

  for (let i = 0; i < 7; i++) {
    const d = new Date(now.getFullYear(), now.getMonth(), now.getDate() + i);
    const parts = getDateParts(d, tz);

    let name = '';
    if (i === 0) name = 'Сегодня';
    else if (i === 1) name = 'Завтра';
    else {
      const weekdays = ['Вс', 'Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб'];
      name = weekdays[d.getDay()];
    }

    const tab = document.createElement('button');
    tab.className = `day-tab ${i === state.selectedDayIndex ? 'active' : ''}`;
    tab.dataset.index = i;
    tab.innerHTML = `
      <span class="day-tab-name">${name}</span>
      <span class="day-tab-date">${parts.day}</span>
      <span class="day-tab-dot" id="day-dot-${i}"></span>
    `;

    tab.addEventListener('click', () => {
      document.querySelectorAll('.day-tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      state.selectedDayIndex = i;
      renderDayTasks();
    });

    daysStripEl.appendChild(tab);
  }
}

/**
 * Загрузка дел с бэкенда GET /api/items
 */
async function loadCalendar() {
  tasksListEl.innerHTML = '<div class="tasks-empty-state">Загрузка дел...</div>';
  const res = await fetchCalendarItems();

  if (!res.ok) {
    tasksListEl.innerHTML = `
      <div class="tasks-empty-state">
        <p>Не удалось загрузить дела</p>
        <button id="btn-reload-tasks" class="btn-small" style="margin-top: 8px;">Повторить</button>
      </div>
    `;
    document.getElementById('btn-reload-tasks')?.addEventListener('click', loadCalendar);
    return;
  }

  state.calendarItems = res.items || [];
  updateDayDots();
  renderDayTasks();
  renderUndatedTasks();
  updateBadge();
}

/**
 * Распределение дел по дням и отрисовка точек
 */
function updateDayDots() {
  const tz = getBrowserTimezone();
  const now = new Date();

  for (let i = 0; i < 7; i++) {
    const targetDate = new Date(now.getFullYear(), now.getMonth(), now.getDate() + i);
    const targetParts = getDateParts(targetDate, tz);

    const hasTasks = state.calendarItems.some(item => {
      const dateStr = item.start || item.deadline;
      if (!dateStr) return false;
      const d = parseIsoDate(dateStr);
      const p = getDateParts(d, tz);
      return p.year === targetParts.year && p.month === targetParts.month && p.day === targetParts.day;
    });

    const dot = document.getElementById(`day-dot-${i}`);
    if (dot) {
      if (hasTasks) dot.classList.add('visible');
      else dot.classList.remove('visible');
    }
  }
}

/**
 * Отрисовка дел выбранного дня
 */
function renderDayTasks() {
  const tz = getBrowserTimezone();
  const now = new Date();
  const targetDate = new Date(now.getFullYear(), now.getMonth(), now.getDate() + state.selectedDayIndex);
  const targetParts = getDateParts(targetDate, tz);

  const dayTasks = state.calendarItems.filter(item => {
    const dateStr = item.start || item.deadline;
    if (!dateStr) return false;
    const d = parseIsoDate(dateStr);
    const p = getDateParts(d, tz);
    return p.year === targetParts.year && p.month === targetParts.month && p.day === targetParts.day;
  });

  // Сортировка: активные сверху, выполненные внизу
  dayTasks.sort((a, b) => {
    if (a.status === 'done' && b.status !== 'done') return 1;
    if (a.status !== 'done' && b.status === 'done') return -1;
    const timeA = new Date(a.start || a.deadline || 0).getTime();
    const timeB = new Date(b.start || b.deadline || 0).getTime();
    return timeA - timeB;
  });

  tasksListEl.innerHTML = '';

  if (dayTasks.length === 0) {
    tasksListEl.innerHTML = '<div class="tasks-empty-state">В этот день дел нет</div>';
    return;
  }

  dayTasks.forEach(task => {
    const card = createTaskCardElement(task);
    tasksListEl.appendChild(card);
  });
}

/**
 * Блок «Без срока»
 */
function renderUndatedTasks() {
  const undated = state.calendarItems.filter(item => !item.start && !item.deadline);

  if (undated.length === 0) {
    undatedSectionEl.classList.add('hidden');
    return;
  }

  undatedSectionEl.classList.remove('hidden');
  undatedListEl.innerHTML = '';

  undated.forEach(task => {
    const card = createTaskCardElement(task);
    undatedListEl.appendChild(card);
  });
}

function createTaskCardElement(task) {
  const isDone = task.status === 'done';
  const el = document.createElement('div');
  el.className = `task-card ${isDone ? 'done' : ''}`;

  const typeLabels = {
    task: 'Задача',
    meeting: 'Встреча',
    reminder: 'Напоминание'
  };

  const typeText = typeLabels[task.type] || 'Дело';
  const tagText = isDone ? (task.type === 'reminder' ? 'Напоминание · выполнено' : 'Выполнено') : typeText;
  const timeFormatted = formatRecordDate(task);

  el.innerHTML = `
    <div class="task-card-header">
      <span class="task-type-tag ${isDone ? 'done' : ''}">${escapeHtml(tagText)}</span>
    </div>
    <div class="task-title ${isDone ? 'done' : ''}">${escapeHtml(task.title)}</div>
    <div class="task-time">${escapeHtml(timeFormatted)}</div>
  `;
  return el;
}

function updateBadge() {
  const tz = getBrowserTimezone();
  const now = new Date();
  const todayParts = getDateParts(now, tz);

  const activeToday = state.calendarItems.filter(item => {
    if (item.status === 'done' || item.status === 'cancelled') return false;
    const dateStr = item.start || item.deadline;
    if (!dateStr) return false;
    const d = parseIsoDate(dateStr);
    const p = getDateParts(d, tz);
    return p.year === todayParts.year && p.month === todayParts.month && p.day === todayParts.day;
  });

  sidebarBadgeEl.textContent = activeToday.length;
}

/**
 * Отправка сообщения
 */
chatFormEl.addEventListener('submit', async (e) => {
  e.preventDefault();
  const text = chatInputEl.value.trim();
  if (!text) {
    chatInputEl.focus();
    chatInputEl.classList.add('shake');
    setTimeout(() => chatInputEl.classList.remove('shake'), 400);
    return;
  }
  if (state.isThinking) return;

  chatInputEl.value = '';
  await handleUserMessage(text);
});

async function handleUserMessage(text) {
  state.lastFailedText = null;
  errorBannerEl.classList.add('hidden');
  emptyChatEl.classList.add('hidden');

  // Добавляем сообщение пользователя
  const userMsg = {
    id: generateId(),
    sender: 'user',
    text
  };
  state.messages.push(userMsg);
  renderMessageRow(userMsg);
  saveChatHistory();
  scrollToBottom();

  // Состояние «думает...»
  setThinking(true);

  // Отправка на бэкенд
  const res = await sendChatMessage(text);
  setThinking(false);

  if (!res.ok) {
    state.lastFailedText = text;
    errorMessageEl.textContent = 'Нет ответа от сервера. Не знаю, выполнено ли — проверьте «Мои дела».';
    errorBannerEl.classList.remove('hidden');
    return;
  }

  // Ответ ассистента
  const assistantMsg = {
    id: generateId(),
    sender: 'assistant',
    text: res.data.reply,
    result: res.data.result
  };

  state.messages.push(assistantMsg);
  renderMessageRow(assistantMsg);
  saveChatHistory();
  scrollToBottom();

  // После каждого ответа чата перезапрашиваем дела в фоне
  loadCalendar();
}

/**
 * Отрисовка сообщения в ленте чата
 */
function renderMessageRow(msg) {
  const row = document.createElement('div');
  row.className = `message-row ${msg.sender}`;

  const bubble = document.createElement('div');
  bubble.className = 'message-bubble';

  const replyText = document.createElement('div');
  replyText.className = 'message-reply';
  replyText.textContent = msg.text || '';
  bubble.appendChild(replyText);

  // Если есть структурный результат (ActionResult)
  if (msg.result && msg.result.ok && msg.result.records && msg.result.records.length > 0) {
    const action = msg.result.action;

    // 1. Создание записи (create_record)
    if (action === 'create_record') {
      const container = document.createElement('div');
      container.className = 'result-container';

      const typeLabels = {
        task: 'Задача создана',
        meeting: 'Встреча создана',
        reminder: 'Напоминание создано'
      };

      msg.result.records.forEach(rec => {
        const card = document.createElement('div');
        card.className = 'result-card';
        card.innerHTML = `
          <span class="tag-success">${escapeHtml(typeLabels[rec.type] || 'Создано')}</span>
          <span class="card-title">${escapeHtml(rec.title)}</span>
          <span class="card-time">${escapeHtml(formatRecordDate(rec))}</span>
        `;
        container.appendChild(card);
      });
      bubble.appendChild(container);
    }

    // 2. Список записей или поиск (list_records, search_records)
    else if (action === 'list_records' || action === 'search_records') {
      const listContainer = document.createElement('div');
      listContainer.className = 'result-list';

      let lastDayKey = null;
      const tz = getBrowserTimezone();

      msg.result.records.forEach((rec, idx) => {
        // Заголовок дня при смене дат
        const dateStr = rec.start || rec.deadline;
        let dayKey = 'Без даты';
        if (dateStr) {
          const d = parseIsoDate(dateStr);
          dayKey = formatDateWords(d, tz);
        }

        if (dayKey !== lastDayKey) {
          const header = document.createElement('div');
          header.className = 'day-header';
          header.textContent = dayKey;
          listContainer.appendChild(header);
          lastDayKey = dayKey;
        }

        const itemRow = document.createElement('div');
        itemRow.className = 'list-item-row';
        const isDone = rec.status === 'done';

        const dateStr = rec.start || rec.deadline;
        let timeStr = '';
        if (dateStr && !rec.all_day) {
          const d = parseIsoDate(dateStr);
          timeStr = formatTime(d, tz);
        } else if (rec.all_day) {
          timeStr = 'весь день';
        }

        itemRow.innerHTML = `
          <div class="list-item-main">
            <span class="item-number">${idx + 1}.</span>
            <span class="item-title ${isDone ? 'done' : ''}">${escapeHtml(rec.title)}</span>
          </div>
          <span class="item-time">${escapeHtml(timeStr || formatRecordDate(rec))}</span>
        `;
        listContainer.appendChild(itemRow);
      });

      bubble.appendChild(listContainer);
    }
  }

  row.appendChild(bubble);
  chatMessagesEl.appendChild(row);
}

function setThinking(val) {
  state.isThinking = val;
  btnSendEl.disabled = val;
  chatInputEl.disabled = val;
  if (val) {
    thinkingIndicatorEl.classList.remove('hidden');
  } else {
    thinkingIndicatorEl.classList.add('hidden');
  }
}

function scrollToBottom() {
  chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight;
}

// Повтор реплики при ошибке сети
btnRetryEl.addEventListener('click', async () => {
  if (!state.lastFailedText) return;
  const text = state.lastFailedText;
  errorBannerEl.classList.add('hidden');
  await loadCalendar(); // перезапрашиваем панель перед повтором
  await handleUserMessage(text);
});

// Нажатие на чипсы-подсказки
document.querySelectorAll('.prompt-chip').forEach(chip => {
  chip.addEventListener('click', () => {
    const text = chip.dataset.text;
    if (text && !state.isThinking) {
      chatInputEl.value = text;
      handleUserMessage(text);
    }
  });
});

// Мобильная шторка «Мои дела»
function toggleMobileSidebar(open) {
  if (open) {
    sidebarEl.classList.add('open');
    backdropEl.classList.remove('hidden');
  } else {
    sidebarEl.classList.remove('open');
    backdropEl.classList.add('hidden');
  }
}

mobileToggleBtn.addEventListener('click', () => toggleMobileSidebar(true));
btnCloseSidebarEl.addEventListener('click', () => toggleMobileSidebar(false));
backdropEl.addEventListener('click', () => toggleMobileSidebar(false));

// Кнопка календаря в шапке
const btnCalendarNavEl = document.getElementById('btn-calendar-nav');
if (btnCalendarNavEl) {
  btnCalendarNavEl.addEventListener('click', () => {
    if (window.innerWidth <= 768) {
      toggleMobileSidebar(true);
    } else {
      daysStripEl?.scrollIntoView({ behavior: 'smooth' });
    }
  });
}

// Кнопка микрофона
const btnMicEl = document.getElementById('btn-mic');
if (btnMicEl) {
  btnMicEl.addEventListener('click', () => {
    chatInputEl.placeholder = 'Голосовой ввод подключается в задаче frontend-02...';
    setTimeout(() => {
      chatInputEl.placeholder = 'Напишите или скажите, что нужно сделать';
    }, 2500);
    chatInputEl.focus();
  });
}

// Модальное окно настроек LLM
btnOpenSettingsEl.addEventListener('click', () => {
  const cfg = getStoredLLMConfig() || {};
  inputBaseUrl.value = cfg.base_url || '';
  inputModel.value = cfg.model || '';
  inputApiKey.value = cfg.api_key || '';
  settingsModalEl.classList.remove('hidden');
});

function closeSettings() {
  settingsModalEl.classList.add('hidden');
}

btnCloseSettingsEl.addEventListener('click', closeSettings);
btnCancelSettingsEl.addEventListener('click', closeSettings);

// Закрытие модалки по клику на затемнение фона
settingsModalEl.addEventListener('click', (e) => {
  if (e.target === settingsModalEl) {
    closeSettings();
  }
});

btnSaveSettingsEl.addEventListener('click', () => {
  const base_url = inputBaseUrl.value.trim();
  const model = inputModel.value.trim();
  const api_key = inputApiKey.value.trim();

  saveStoredLLMConfig({ base_url, model, api_key });
  closeSettings();
});

function initEventListeners() {
  // ESC закрывает модалку и мобильную шторку
  window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      closeSettings();
      toggleMobileSidebar(false);
    }
  });
}

function generateId() {
  return 'msg_' + Math.random().toString(36).substring(2, 9);
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
