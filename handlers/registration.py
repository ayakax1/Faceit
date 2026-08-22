from aiogram import Router, F, Bot
from aiogram.filters import CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

import database as db
import keyboards as kb
from config import ADMIN_ID
from states import Registration
from utils import room_link

router = Router()


async def send_main_menu(message: Message):
    is_admin = message.from_user.id == ADMIN_ID
    await message.answer(
        "Главное меню:",
        reply_markup=kb.main_menu(is_admin=is_admin),
    )


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, state: FSMContext):
    tg_id = message.from_user.id

    banned_until = await db.is_banned(tg_id)
    if banned_until:
        await message.answer(
            f"⛔ Вы забанены до {banned_until[:16].replace('T', ' ')} (UTC) за подделку данных при регистрации."
        )
        return

    registered = await db.is_registered(tg_id)

    # Если пришли по ссылке комнаты (room_<id>) — обработает room.py, но сперва
    # нужно убедиться, что пользователь зарегистрирован.
    deep_arg = command.args

    if not registered:
        pending = await db.get_pending_verification(tg_id)
        if pending:
            await message.answer(
                "Ваша заявка уже отправлена на проверку администратору. Ожидайте решения."
            )
            return
        await state.set_state(Registration.waiting_bs_id)
        await state.update_data(deep_arg=deep_arg)
        await message.answer(
            "Добро пожаловать в Faceit: Block Strike!\n\n"
            "Перед началом нужно пройти проверку. Пришлите ваш <b>BS ID</b>."
        )
        return

    if deep_arg and deep_arg.startswith("room_"):
        # передаём управление room.py через прямой вызов (см. router include order)
        from handlers.room import handle_room_join_by_id

        room_id = int(deep_arg.split("_", 1)[1])
        await handle_room_join_by_id(message, room_id)
        return

    await send_main_menu(message)


@router.message(Registration.waiting_bs_id)
async def reg_bs_id(message: Message, state: FSMContext):
    await state.update_data(bs_id=message.text.strip())
    await state.set_state(Registration.waiting_bs_nickname)
    await message.answer("Теперь пришлите ваш <b>BS nickname</b>.")


@router.message(Registration.waiting_bs_nickname)
async def reg_bs_nickname(message: Message, state: FSMContext):
    await state.update_data(bs_nickname=message.text.strip())
    await state.set_state(Registration.waiting_tg_user)
    await message.answer("И последнее — пришлите ваш <b>юзернейм в Telegram</b> (например, @ivanov).")


@router.message(Registration.waiting_tg_user)
async def reg_tg_user(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    bs_id = data["bs_id"]
    bs_nickname = data["bs_nickname"]
    tg_user_input = message.text.strip()
    tg_id = message.from_user.id

    await db.create_pending_verification(tg_id, bs_id, bs_nickname, tg_user_input)
    await state.clear()

    await message.answer(
        "Заявка отправлена администратору на проверку. Как только вас одобрят — "
        "сможете создавать комнаты. Это может занять некоторое время."
    )

    await bot.send_message(
        ADMIN_ID,
        "🆕 <b>Новая заявка на верификацию</b>\n\n"
        f"TG ID: <code>{tg_id}</code>\n"
        f"TG username (аккаунт): @{message.from_user.username or '—'}\n"
        f"Указанный TG user: {tg_user_input}\n"
        f"BS ID: {bs_id}\n"
        f"BS nickname: {bs_nickname}",
        reply_markup=kb.verification_review_kb(tg_id),
    )


@router.callback_query(F.data.startswith("verify_ok:"))
async def verify_ok(callback: CallbackQuery, bot: Bot):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Только для администратора.", show_alert=True)
        return
    tg_id = int(callback.data.split(":")[1])
    await db.approve_verification(tg_id)
    await callback.message.edit_text(callback.message.text + "\n\n✅ Одобрено.")
    await bot.send_message(tg_id, "✅ Вы прошли проверку! Открываю меню — используйте /start.")
    await callback.answer()


@router.callback_query(F.data.startswith("verify_ban:"))
async def verify_ban(callback: CallbackQuery, bot: Bot):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Только для администратора.", show_alert=True)
        return
    from config import BAN_DAYS

    tg_id = int(callback.data.split(":")[1])
    await db.ban_player(tg_id, BAN_DAYS)
    await callback.message.edit_text(callback.message.text + f"\n\n🚫 Бан на {BAN_DAYS} дней.")
    await bot.send_message(tg_id, f"🚫 Ваши данные при регистрации оказались недостоверны. Бан на {BAN_DAYS} дней.")
    await callback.answer()
