document.querySelectorAll('[data-password-toggle]').forEach((button) => {
    button.addEventListener('click', () => {
        const input = document.getElementById(button.dataset.target);
        const isVisible = input.type === 'text';

        input.type = isVisible ? 'password' : 'text';
        button.setAttribute('aria-label', isVisible ? 'Показать пароль' : 'Скрыть пароль');
        button.setAttribute('title', isVisible ? 'Показать пароль' : 'Скрыть пароль');
    });
});