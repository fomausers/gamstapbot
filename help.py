from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters import Command

router = Router()

# --- КЛАВИАТУРЫ ---

# Главное меню помощи
def get_help_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎮 Игры", callback_data="help_games")],
        [InlineKeyboardButton(text="⌨️ Команды", callback_data="help_cmds")]
    ])

# Меню выбора игр
def get_games_selection_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💣 Мины", callback_data="game_mines")],
        [InlineKeyboardButton(text="🏀 Баскет", callback_data="game_bask")],
        [InlineKeyboardButton(text="🎰 Рулетка", callback_data="game_roulette")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="help_main")]
    ])

# Кнопка возврата в меню игр
def get_back_to_games_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="help_games")]
    ])

# --- ТЕКСТОВЫЕ БЛОКИ ---

HELP_TEXT_MAIN = "<blockquote>❓ <b>Выберите интересующий вас раздел помощи:</b></blockquote>"

HELP_TEXT_CMDS = (
    "<blockquote>⌨️ <b>Раздел: Общие команды</b></blockquote>\n\n"
    "<code>б</code> — проверить свой баланс\n"
    "<code>п (сумма)</code> — передать валюту (ответом на сообщение)\n"
    "<code>профиль</code> — просмотр своей анкеты\n"
    "<code>Бонус</code> — получить ежедневную награду"
)

HELP_TEXT_GAMES_MAIN = "<blockquote>🎮 <b>Выберите игру для получения справки:</b></blockquote>"

# Тексты для каждой игры
TEXT_GAME_MINES = (
    "<blockquote>💣 <b>Игра: Мины</b></blockquote>\n\n"
    "<code>мины (сумма)</code> — начать игру на указанную ставку.\n"
    "<i>После запуска следуйте инструкциям в кнопках.</i>"
)

TEXT_GAME_BASK = (
    "<blockquote>🏀 <b>Игра: Баскет</b></blockquote>\n\n"
    "<code>баскет (сумма)</code> — сделать ставку.\n"
    "<code>баскет вб</code> — поставить весь баланс.\n\n"
    "<i>Результат зависит от того, попадет ли мяч в корзину.</i>"
)

TEXT_GAME_ROULETTE = (
    "<blockquote>🎰 <b>Игра: Рулетка</b></blockquote>\n\n"
    "<code>(сумма) (тип)</code> — сделать ставку (красное/черное/число).\n"
    "<code>го</code> — запустить рулетку.\n"
    "<code>лог</code> — история последних чисел.\n"
    "<code>ставки</code> — ваши активные ставки."
)

# --- ХЕНДЛЕРЫ ---

@router.message(Command("help"))
@router.message(F.text == "❓ Помощь")
async def help_main(message: Message):
    await message.answer(HELP_TEXT_MAIN, parse_mode="HTML", reply_markup=get_help_main_kb())

@router.callback_query(F.data == "help_main")
async def help_main_callback(callback: CallbackQuery):
    await callback.message.edit_text(HELP_TEXT_MAIN, parse_mode="HTML", reply_markup=get_help_main_kb())
    await callback.answer()

# Раздел команд
@router.callback_query(F.data == "help_cmds")
async def help_cmds(callback: CallbackQuery):
    await callback.message.edit_text(HELP_TEXT_CMDS, parse_mode="HTML",
                                     reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="help_main")]]))
    await callback.answer()

# Раздел выбора игр
@router.callback_query(F.data == "help_games")
async def help_games_main(callback: CallbackQuery):
    await callback.message.edit_text(HELP_TEXT_GAMES_MAIN, parse_mode="HTML", reply_markup=get_games_selection_kb())
    await callback.answer()

# Подразделы игр
@router.callback_query(F.data == "game_mines")
async def help_game_mines(callback: CallbackQuery):
    await callback.message.edit_text(TEXT_GAME_MINES, parse_mode="HTML", reply_markup=get_back_to_games_kb())
    await callback.answer()

@router.callback_query(F.data == "game_bask")
async def help_game_bask(callback: CallbackQuery):
    await callback.message.edit_text(TEXT_GAME_BASK, parse_mode="HTML", reply_markup=get_back_to_games_kb())
    await callback.answer()

@router.callback_query(F.data == "game_roulette")
async def help_game_roulette(callback: CallbackQuery):
    await callback.message.edit_text(TEXT_GAME_ROULETTE, parse_mode="HTML", reply_markup=get_back_to_games_kb())
    await callback.answer()