document.querySelectorAll('.menu-item').forEach(item => {
    item.addEventListener('click', () => {
        let target = item.getAttribute('data-target');
        if (target === 'settings') {
            getSettings();
        }
        document.querySelectorAll('.tab-content').forEach(content => {
            if (content.id === target) {
                content.classList.remove('is-hidden');
            } else {
                content.classList.add('is-hidden');
            }
        });
        document.querySelector('.menu-item.is-active').classList.remove('is-active');
        item.classList.add('is-active');
    });
});

function updateSetting(setting, value) {
    fetch(`/api/settings/`, {
        method: 'PUT',
        body: JSON.stringify({
            [setting]: value
        }),
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        }
    }).then(response => {
        if (!response.ok) {
            console.log('Failed to update setting');
        }
    });
}

function getSettings() {
    fetch('/api/settings/').then(response => {
        if (response.ok) {
            return response.json();
        }
    }).then(data => {
        for (let setting in data) {
            if (document.querySelector(`[data-name="${setting}"]`).type === 'checkbox') {
                document.querySelector(`[data-name="${setting}"]`).checked = data[setting];
            } else {
                document.querySelector(`[data-name="${setting}"]`).value = data[setting];
            }
        }
    });

}

document.querySelectorAll('.settings-input').forEach(input => {
    input.addEventListener('change', e => {
        if (e.target.type === 'checkbox') {
            updateSetting(e.target.dataset.name, e.target.checked);
        } else if (e.target.type === 'number' || e.target.type === 'range') {
            if (e.target.value < parseInt(e.target.min, 10)) {
                e.target.value = e.target.min;
            }
            updateSetting(e.target.dataset.name, parseInt(e.target.value, 10))
        } else {
            updateSetting(e.target.dataset.name, e.target.value);
        }
    });
});