let questions = [];
let reoccurrences = [];
let currentQuestionId = null;
let currentQuestionData = null;
let correctAnswersCount = 0;
let wrongAnswersCount = 0;
let isQuizFinished = false;
let startTime = new Date();
let studyTime = 0;
const source = quizUrl;
const sourceProperties = {
    "title": null,
    "description": null,
    "maintainer": null,
    "version": 1
};
let stopProgressSaving = false;

let peer
let peerConnections = [];
let isContinuityHost = false;


document.addEventListener('DOMContentLoaded', async () => {
    await loadProgress();
    fetchQuestions().then(success => {
        if (!success) {
            document.getElementById('info').innerHTML = `
                <div class="alert alert-danger alert-dismissible fade show" role="alert">
                    Błąd ładowania pytań. Spróbuj ponownie za chwilę lub upewnij się, że adres URL jest poprawny.
                    <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
                </div>
            `;
            return;
        }
        if (questions.length === 0) {
            document.getElementById('info').innerHTML = `
                <div class="alert alert-danger alert-dismissible fade show" role="alert">
                    Ta baza nie zawiera żadnych pytań. Skontaktuj się z autorem bazy.
                    <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
                </div>
            `;
            return;
        }
        if (isQuizFinished) {
            document.getElementById('info').innerHTML = `
                <div class="alert alert-success alert-dismissible fade show" role="alert">
                    Gratulacje! Opanowałeś wszystkie pytania.\nZresetuj postępy aby zacząć od nowa.
                    <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
                </div>
            `;
        } else {
            if (!currentQuestionId) {
                currentQuestionId = getRandomQuestionId();
            }
            loadQuestion(currentQuestionId);
            setInterval(updateStudyTime, 1000);
        }
        const params = new URLSearchParams(window.location.search);
        if (params.has('question')) {
            const questionId = parseInt(params.get('question'), 10);
            loadQuestion(questionId);
            params.delete('question');
            window.history.replaceState({}, document.title, `${window.location.pathname}?${params.toString()}`);
        }
    });

    document.getElementById('nextButton').addEventListener('click', handleNextButtonClick);
    document.getElementById('reportButton').addEventListener('click', () => reportIncorrectQuestion(currentQuestionId));
    document.getElementById('resetButton').addEventListener('click', async () => {
        if (confirm('Czy na pewno chcesz zresetować postępy?')) {
            await resetProgress();
            window.location.reload();
        }
    });

    document.getElementById('clipboardButton').addEventListener('click', copyToClipboard);
    document.getElementById('chatGPTButton').addEventListener('click', openInChatGPT);

    document.addEventListener('keydown', handleKeyPress);

    initiateContinuity()
    setInterval(pingPeers, pingInterval);
});

const fetchQuestions = async () => {
    try {
        const response = await fetch(source);
        const data = await response.json();

        questions = Array.isArray(data) ? data : data.questions || [];
        if (reoccurrences.length === 0) {
            reoccurrences = questions.map(q => ({id: q.id, reoccurrences: userSettings.initialRepetitions}));
        }
        document.getElementById('totalQuestions').textContent = questions.length;

        if (new URLSearchParams(window.location.search).has('delulu')) {
            document.getElementById('totalQuestions').textContent = 69;
        }

        for (const key in sourceProperties) {
            if (data[key]) {
                sourceProperties[key] = data[key];
            }
        }

        if (sourceProperties.title) {
            document.title = `Testownik - ${sourceProperties.title}`;
        }

        handleVersionUpdate();
        if (sourceProperties.report_email) {
            document.getElementById('reportButton').style.display = 'inline-block';
        }
        return true;
    } catch (error) {
        console.error('Error fetching questions:', error);
        return false;
    }
};

const handleVersionUpdate = () => {
    const storedVersion = localStorage.getItem(`${source}_version`);
    const localStorageVersion = storedVersion ? parseInt(storedVersion) : sourceProperties.version;

    if (!storedVersion) {
        localStorage.setItem(`${source}_version`, sourceProperties.version);
    }

    if (sourceProperties.version !== localStorageVersion) {
        document.getElementById('info').innerHTML = `
            <div class="alert alert-success alert-dismissible fade show" role="alert">
                Baza pytań została zaktualizowana.
                <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
            </div>
        `;
        localStorage.setItem(`${source}_version`, sourceProperties.version);
    }
};

const shuffleArray = array => {
    for (let i = array.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [array[i], array[j]] = [array[j], array[i]];
    }
    return array;
};

const loadQuestion = (id, answersOrder = [], sendToPeers = true) => {
    currentQuestionData = questions.find(q => q.id === id);
    if (!currentQuestionData) {
        alert('Nie znaleziono pytania o podanym identyfikatorze.');
        return;
    }
    const questionText = document.getElementById('questionText');
    const buttonContainer = document.getElementById('buttonContainer');
    const questionImage = document.getElementById('questionImage');
    const feedback = document.getElementById('feedback');
    const explanation = document.getElementById('explanation');
    const nextButton = document.getElementById('nextButton');

    questionText.textContent = `${currentQuestionData.id}. ${currentQuestionData.question}`;
    buttonContainer.innerHTML = '';
    feedback.innerHTML = '';
    explanation.innerHTML = '';
    nextButton.textContent = 'Sprawdź';

    if (answersOrder.length > 0) {
        currentQuestionData.answers.sort((a, b) => answersOrder.indexOf(a.answer) - answersOrder.indexOf(b.answer));
    } else {
        // Shuffle the answers before displaying them
        currentQuestionData.answers = shuffleArray([...currentQuestionData.answers]);
    }

    currentQuestionData.answers.forEach((answer, idx) => {
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.className = 'btn-check';
        checkbox.id = `btn-check-${idx}`;
        checkbox.name = 'answer';
        checkbox.value = answer.correct;
        checkbox.autocomplete = 'off';
        checkbox.onclick = () => handleCheckboxClick(checkbox, currentQuestionData.multiple);
        checkbox.dataset.key = answer.answer + answer.image;

        const label = document.createElement('label');
        label.className = 'btn btn-outline-secondary btn-block';
        label.style.color = 'var(--bs-body-color)';
        label.setAttribute('for', `btn-check-${idx}`);

        // Check if the answer contains an image
        if (answer.image) {
            const img = document.createElement('img');
            img.src = answer.image;
            img.alt = 'Answer Image';
            img.className = 'img-fluid';
            img.onerror = () => {
                img.style.display = 'none';
                const errorText = document.createElement('p');
                errorText.className = 'text-danger';
                errorText.textContent = "Błąd ładowania zdjęcia!";
                label.appendChild(errorText);
            };
            label.appendChild(img);
        }

        if (answer.answer) {
            const answerText = document.createTextNode(answer.answer);
            label.appendChild(answerText);
        } else if (!answer.image) {
            const errorText = document.createElement('p');
            errorText.className = 'text-danger';
            errorText.textContent = "Brak treści odpowiedzi!";
            label.appendChild(errorText);
        }

        buttonContainer.appendChild(checkbox);
        buttonContainer.appendChild(label);
    });

    if (currentQuestionData.image) {
        const imageUrl = currentQuestionData.image;
        questionImage.innerHTML = imageUrl ? `<img src="${imageUrl}" alt="Question Image" class="img-fluid">` : '';
        if (questionImage.querySelector('img')) {
            questionImage.querySelector('img').onerror = () => {
                questionImage.innerHTML = '';
            };
        }
    } else {
        questionImage.innerHTML = '';
    }

    if (sendToPeers) {
        sendToAllPeers({
            type: 'question_loaded',
            questionId: currentQuestionData.id,
            answersOrder: currentQuestionData.answers.map(answer => answer.answer)
        });
    }

    saveProgress();
};

const getRandomQuestionId = () => {
    // Get random question id from reoccurrences that is not 0
    const questionIds = reoccurrences.filter(q => q.reoccurrences > 0).map(q => q.id);
    if (questionIds.length === 0) {
        isQuizFinished = true;
        return null;
    }
    return questionIds[Math.floor(Math.random() * questionIds.length)];
}

const handleCheckboxClick = (clickedCheckbox, isMultiple, remote = false) => {
    if (!isMultiple) {
        document.querySelectorAll('input[name="answer"]').forEach(checkbox => {
            if (checkbox !== clickedCheckbox) {
                checkbox.checked = false;
            }
        });
    }
    if (!remote) {
        sendToAllPeers({
            type: 'answer_selected',
            answer: clickedCheckbox.dataset.key
        });
    } else {
        clickedCheckbox.checked = !clickedCheckbox.checked;
    }
    clickedCheckbox.labels[0].style.color = clickedCheckbox.checked ? 'var(--bs-light)' : 'var(--bs-body-color)';
};

const handleNextButtonClick = () => {
    const nextButton = document.getElementById('nextButton');
    if (nextButton.textContent === 'Sprawdź') {
        checkAnswer();
    } else {
        nextQuestion();
    }
};

const checkAnswer = (remote = false) => {
    const selectedCheckboxes = document.querySelectorAll('input[name="answer"]:checked');
    const feedback = document.getElementById('feedback');
    const explanation = document.getElementById('explanation');
    const nextButton = document.getElementById('nextButton');
    const buttonContainer = document.getElementById('buttonContainer');

    let allCorrect = true;
    let hasSelectedCorrect = false;
    const correctAnswers = currentQuestionData.answers.filter(answer => answer.correct);
    const selectedAnswers = Array.from(selectedCheckboxes).map(checkbox => checkbox.dataset.key);

    correctAnswers.forEach(answer => {
        if (!selectedAnswers.includes(answer.answer + answer.image)) {
            allCorrect = false;
        }
    });

    selectedCheckboxes.forEach(selectedCheckbox => {
        const isCorrect = selectedCheckbox.value === 'true';
        if (isCorrect) {
            hasSelectedCorrect = true;
            selectedCheckbox.nextSibling.classList.replace('btn-outline-secondary', 'btn-success');
        } else {
            allCorrect = false;
            selectedCheckbox.nextSibling.classList.replace('btn-outline-secondary', 'btn-danger');
        }
    });

    if (allCorrect && hasSelectedCorrect) {
        feedback.textContent = 'Poprawna odpowiedź!';
        feedback.className = 'text-success';
        correctAnswersCount++;
        reoccurrences.find(q => q.id === currentQuestionData.id).reoccurrences--;
    } else {
        feedback.innerHTML = selectedCheckboxes.length === 0 ? 'Brak odpowiedzi!' : 'Zła odpowiedź!';

        explanation.textContent = '';

        if (currentQuestionData.explanation) {
            explanation.innerHTML = marked.parse(currentQuestionData.explanation.replaceAll('\\(', '\\\\(').replaceAll('\\)', '\\\\)').replaceAll('\\[', '\\\\[').replaceAll('\\]', '\\\\]'));
            renderMathInElement(explanation);
        }

        feedback.className = 'text-danger';
        // Highlight correct answers that were not selected
        buttonContainer.querySelectorAll('input[value="true"]').forEach(correctCheckbox => {
            correctCheckbox.nextSibling.classList.replace('btn-outline-secondary', 'btn-success');
        });
        wrongAnswersCount++;
        reoccurrences.find(q => q.id === currentQuestionData.id).reoccurrences += userSettings.wrongAnswerRepetitions;
    }

    document.getElementById('providedAnswers').textContent = wrongAnswersCount + correctAnswersCount;
    document.getElementById('masteredQuestions').textContent = reoccurrences.filter(q => q.reoccurrences === 0).length;
    nextButton.textContent = 'Następne';
    saveProgress();
    if (!remote) {
        sendToAllPeers({
            type: 'answer_checked'
        });
    }
};

const nextQuestion = () => {
    currentQuestionId = getRandomQuestionId();
    if (currentQuestionId) {
        loadQuestion(currentQuestionId);
    } else {
        alert('Wszystkie pytania zostały opanowane, zresetuj postępy aby zacząć od nowa.');
    }
};

const updateStudyTime = () => {
    const currentTime = new Date();
    const timeDiff = Math.floor((currentTime - startTime) / 1000);
    studyTime = timeDiff;
    const hours = String(Math.floor(timeDiff / 3600)).padStart(2, '0');
    const minutes = String(Math.floor((timeDiff % 3600) / 60)).padStart(2, '0');
    const seconds = String(timeDiff % 60).padStart(2, '0');
    document.getElementById('studyTime').textContent = `${hours}:${minutes}:${seconds}`;
    saveProgress(false);
};

const saveProgress = async (cloudSync = true) => {
    if (stopProgressSaving || isQuizFinished || document.hidden) return;
    const progress = {
        currentQuestionId,
        wrongAnswersCount,
        correctAnswersCount,
        studyTime,
        reoccurrences,
    };
    localStorage.setItem(`${source}_progress`, JSON.stringify(progress));

    if (cloudSync && userSettings.syncProgress && userAuthenticated) {
        await fetch(`${source}progress/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify({
                current_question: currentQuestionId,
                correct_answers_count: correctAnswersCount,
                wrong_answers_count: wrongAnswersCount,
                study_time: studyTime,
                reoccurrences,
            })
        });
    }
};

// first load progress from localstorage and after that try to load from server if sync is enabled
const loadProgress = async () => {
    const progress = JSON.parse(localStorage.getItem(`${source}_progress`));
    if (progress) {
        currentQuestionId = progress.currentQuestionId;
        correctAnswersCount = progress.correctAnswersCount;
        wrongAnswersCount = progress.wrongAnswersCount;
        studyTime = progress.studyTime || 0;
        startTime = new Date(new Date() - studyTime * 1000);
        reoccurrences = progress.reoccurrences;
        updateStudyTime()
    }

    document.getElementById('providedAnswers').textContent = wrongAnswersCount + correctAnswersCount || 0;
    document.getElementById('masteredQuestions').textContent = reoccurrences.filter(q => q.reoccurrences === 0).length || 0;

    if (userSettings.syncProgress && userAuthenticated) {
        const response = await fetch(`${source}progress/`);
        if (response.ok) {
            const data = await response.json();
            if (data) {
                currentQuestionId = data.current_question;
                correctAnswersCount = data.correct_answers_count;
                wrongAnswersCount = data.wrong_answers_count;
                studyTime = data.study_time || 0;
                startTime = new Date(new Date() - studyTime * 1000);
                reoccurrences = data.reoccurrences;
                updateStudyTime();
            }
        }
    }
};

const resetProgress = async () => {
    stopProgressSaving = true;
    localStorage.removeItem(`${source}_progress`);
    localStorage.removeItem(`${source}_version`);
    if (userSettings.syncProgress && userAuthenticated) {
        await fetch(`${source}progress/`, {
            method: 'DELETE',
            headers: {
                'X-CSRFToken': csrfToken
            }
        });
    }
};


const reportIncorrectQuestion = questionId => {
    const questionData = questions.find(q => q.id === questionId);
    const subject = encodeURIComponent(`Testownik ${source} - zgłoszenie błędu`);
    const body = encodeURIComponent(`Pytanie nr ${questionData.id}:\n${questionData.question}\n\nOdpowiedzi:\n${questionData.answers.map(answer => answer.answer + (answer.correct ? ' (poprawna)' : '')).join('\n')}\n\n\nNapisz tutaj swoje uwagi lub poprawną odpowiedź:\n`);
    const email = sourceProperties.report_email;
    if (!email) {
        alert('Brak adresu e-mail do zgłaszania błędów.');
        return;
    }

    window.open(`mailto:${email}?subject=${subject}&body=${body}`);
};

const handleKeyPress = event => {
    const activeElement = document.activeElement;
    if (event.target.tagName.toLowerCase() === 'input' && event.target.type !== 'checkbox') return;

    const key = event.key.toLowerCase();
    if (key === 's') {
        nextQuestion();
    } else if (key === 'enter') {
        if (activeElement.tagName.toLowerCase() === 'button') {
            return;
        }
        handleNextButtonClick();
    } else if (key >= '1' && key <= '9') {
        const index = parseInt(key, 10) - 1;
        const checkboxes = document.querySelectorAll('input[name="answer"]');
        if (checkboxes[index]) {
            checkboxes[index].click();
        }
    } else if (key === 'c' && !event.ctrlKey) {
        document.getElementById('continuityButton').classList.remove('d-none');
    }
};


const copyToClipboard = () => {
    try {
        const {question, answers} = currentQuestionData;
        const answersText = answers.map((answer, idx) => `Odpowiedź ${idx + 1}: ${answer.answer} (Poprawna: ${answer.correct ? 'Tak' : 'Nie'})`).join('\n');
        const fullText = `${question}\n\n${answersText}`;

        navigator.clipboard.writeText(fullText).then(() => {
            bootstrap.Toast.getOrCreateInstance(document.getElementById('copiedToast')).show();
        }).catch(err => {
            console.error('Could not copy text: ', err);
        });
    } catch (error) {
        console.error('Error copying to clipboard:', error);
        bootstrap.Toast.getOrCreateInstance(document.getElementById('errorToast')).show();

    }
};

const openInChatGPT = () => {
    try {
        const {question, answers} = currentQuestionData;
        const answersText = answers.map((answer, idx) => `Odpowiedź ${idx + 1}: ${answer.answer} (Poprawna: ${answer.correct ? 'Tak' : 'Nie'})`).join('\n');
        const fullText = `Pytanie: ${question}\n\nOdpowiedzi:\n${answersText}`;
        const chatGPTUrl = `https://chat.openai.com/?q=${encodeURIComponent(fullText)}`;

        window.open(chatGPTUrl, '_blank');
    } catch (error) {
        console.error('Error opening in ChatGPT:', error);
        bootstrap.Toast.getOrCreateInstance(document.getElementById('errorToast')).show();
    }
};


// Continuity feature

const pingInterval = 5000; // 5 seconds
const pingTimeout = 15000; // 15 seconds

const initiateContinuity = () => {
    // Only initiate continuity if the user is authenticated and sync is enabled
    if (!userAuthenticated || !userSettings.syncProgress) {
        return;
    }
    // First, create a new Peer with ID from userId and quizUrl, if already exists then try to connect to it
    peer = new peerjs.Peer(
        `${source.replaceAll('/', '')}_${userId}`,
        {
            config: {
                iceServers: [
                    {urls: 'stun:stun.l.google.com:19302'},
                    {urls: 'stun:stun1.l.google.com:19302'},
                    {urls: 'turn:freeturn.net:3478', username: 'free', credential: 'free'}
                ]
            }
        });

    peer.on('error', function (err) {
        if (err.type === 'unavailable-id') {
            isContinuityHost = false;
            peer = new peerjs.Peer(
                {
                    config: {
                        iceServers: [
                            {urls: 'stun:stun.l.google.com:19302'},
                            {urls: 'stun:stun1.l.google.com:19302'},
                            {urls: 'turn:freeturn.net:3478', username: 'free', credential: 'free'}
                        ]
                    }
                });

            peer.on('error', function (err) {
                console.error('Peer error:', err);
            });

            peer.on('open', function (id) {
                // If the Peer ID is already taken, try to connect to the existing one
                connectToPeer(`${source.replaceAll('/', '')}_${userId}`).then(conn => {
                    console.log('Connected to peer:', conn);
                    conn.on('data', data => handlePeerData(conn, data));
                    conn.on('error', error => {
                        console.error('Error connecting to peer:', error);
                    });
                    conn.on('close', handlePeerClose);
                    conn.on('disconnected', handlePeerClose);
                    bootstrap.Toast.getOrCreateInstance(document.getElementById('continuityConnectedToast')).show();
                }).catch(error => {
                    console.error('Error connecting to peer:', error);
                    alert("Nie udało się połączyć z urządzeniem. Spróbuj ponownie lub zaimportuj dane zamiast tego.");
                });
                updateContinuityModal();
            });

            peer.on('connection', handlePeerConnection);
        } else {
            console.error('Peer error:', err);
        }
    });

    peer.on('open', function (id) {
        isContinuityHost = true;
        updateContinuityModal();
    });

    peer.on('connection', handlePeerConnection);
}

const handlePeerConnection = (conn) => {
    console.log('Connection established:', conn);
    peerConnections.push(conn);
    updateContinuityModal(true);
    conn.on('data', data => handlePeerData(conn, data));
    conn.on('error', function (err) {
        console.error('Connection error:', err);
    });
    conn.on('close', handlePeerClose);
    conn.on('disconnected', handlePeerClose);
    conn.on('open', function () {
        bootstrap.Toast.getOrCreateInstance(document.getElementById('continuityConnectedToast')).show();
        sendToPeer(conn, {
            type: 'progress_sync',
            studyTime,
            wrongAnswersCount,
            correctAnswersCount,
            reoccurrences,
        });
        sendToPeer(conn, {
            type: 'question_loaded',
            questionId: currentQuestionData.id,
            answersOrder: currentQuestionData.answers.map(answer => answer.answer)
        });
        sendToPeer(conn, {
            type: 'device_info',
            metadata: {
                device: getDeviceFriendlyName(),
                type: getDeviceType()
            }
        });
        const selectedCheckboxes = document.querySelectorAll('input[name="answer"]:checked');
        selectedCheckboxes.forEach(checkbox => {
            sendToPeer(conn, {
                type: 'answer_selected',
                answer: checkbox.dataset.key
            });
        });
    });
};

const handlePeerClose = (conn) => {
    console.log('Connection closed:', conn);
    peerConnections = peerConnections.filter(c => c.open);
    updateContinuityModal();
    // If the host connection is closed, try to become the host and wait for other devices to connect, otherwise try to connect to the host
    if (!isContinuityHost) {
        initiateContinuity();
    }
    bootstrap.Toast.getOrCreateInstance(document.getElementById('continuityDisconnectedToast')).show();
}

const handlePeerData = (conn, data) => {
    console.log('Received data from peer:', data);
    sendToAllPeersExcept(conn, data);
    switch (data.type) {
        case 'ping':
            sendToPeer(conn, {type: 'pong'});
            break;
        case 'pong':
            clearTimeout(conn.pingTimeout);
            break;
        case 'device_info':
            conn.metadata = data.metadata;
            updateContinuityModal();
            break;
        case 'progress_sync':
            studyTime = data.studyTime;
            startTime = new Date(new Date() - studyTime * 1000);
            wrongAnswersCount = data.wrongAnswersCount;
            correctAnswersCount = data.correctAnswersCount;
            reoccurrences = data.reoccurrences;
            document.getElementById('masteredQuestions').textContent = reoccurrences.filter(q => q.reoccurrences === 0).length;
            document.getElementById('providedAnswers').textContent = wrongAnswersCount + correctAnswersCount;
            saveProgress();
            break;
        case 'question_loaded':
            if (currentQuestionData && currentQuestionData.id === data.questionId) {
                if (data.answersOrder.length > 0) {
                    if (currentQuestionData.answers.map(answer => answer.answer).join(',') !== data.answersOrder.join(',')) {
                        loadQuestion(currentQuestionData.id, data.answersOrder);
                    }
                }
                return;
            }
            loadQuestion(data.questionId, data.answersOrder, false);
            break;
        case 'answer_selected':
            const checkbox = document.querySelector(`input[data-key="${data.answer}"]`);
            if (checkbox) {
                handleCheckboxClick(checkbox, currentQuestionData.multiple, true);
            }
            break;
        case 'answer_checked':
            checkAnswer(true);
            break;
        default:
            console.error('Unknown data type:', data.type);
    }
}


const getPeerId = () => {
    return new Promise((resolve, reject) => {
        if (peer.id) {
            resolve(peer.id);
        } else {
            peer.on('open', () => {
                resolve(peer.id);
            });
        }
    });
}

const connectToPeer = (peerId) => {
    return new Promise((resolve, reject) => {
        // Wait for the Peer instance to be open
        if (peer.open) {
            initiateConnection();
        } else {
            peer.on('open', initiateConnection);
            peer.on('error', reject);
        }

        function initiateConnection() {
            const conn = peer.connect(peerId, {
                metadata: {
                    device: getDeviceFriendlyName(),
                    type: getDeviceType()
                }
            });
            conn.on('open', () => {
                peerConnections.push(conn);
                updateContinuityModal();
                resolve(conn);
            });
            conn.on('error', reject);
        }
    });
};

const sendToPeer = (conn, data) => {
    console.log('Sending data to peer:', data);
    conn.send(data);
}

const sendToAllPeers = (data) => {
    peerConnections.forEach(conn => {
        sendToPeer(conn, data);
    });
}

const sendToAllPeersExcept = (exceptConn, data) => {
    peerConnections.forEach(conn => {
        if (conn !== exceptConn) {
            sendToPeer(conn, data);
        }
    });
}

const pingPeers = () => {
    peerConnections.forEach(conn => {
        if (conn.open) {
            sendToPeer(conn, {type: 'ping'});
            conn.pingTimeout = setTimeout(() => {
                console.log('Ping timeout, closing connection:', conn);
                conn.close();
            }, pingTimeout);
        }
    });
};

const getDeviceFriendlyName = () => {
    const parser = new UAParser();
    const ua = parser.getResult();
    if (ua.device.type === 'tablet') {
        if (ua.device.model === 'iPad' || ua.os.name === 'iOS' || ua.os.name === 'Mac OS') {
            return 'iPad';
        }
        return 'Tablet';
    }
    if (ua.device.type === 'mobile') {
        if (ua.os.name === 'iOS') {
            return 'iPhone';
        }
        return 'Telefon';
    }
    if (ua.os.name === 'Mac OS') {
        return 'Mac';
    }
    return 'Komputer';
}

const getDeviceType = () => {
    const parser = new UAParser();
    const ua = parser.getResult();
    if (ua.device.type === 'tablet') {
        return 'tablet';
    }
    if (ua.device.type === 'mobile') {
        return 'mobile';
    }
    return 'desktop';
}

const updateContinuityModal = (autoClose = false) => {
    const continuityNotConnectedDiv = document.getElementById('continuityNotConnectedDiv');
    const continuityConnectedDiv = document.getElementById('continuityConnectedDiv');
    const continuityConnectedName = document.getElementById('continuityConnectedName');
    const continuityButton = document.getElementById('continuityButton');
    const continuityIcon = document.getElementById('continuityIcon');

    if (peerConnections.length === 0) {
        continuityButton.classList.add('d-none');
        continuityNotConnectedDiv.classList.remove('d-none');
        continuityConnectedDiv.classList.add('d-none');
        if (peerConnections.length === 0) {
            continuityIcon.icon = 'flat-color-icons:multiple-devices';
        }
    } else {
        continuityButton.classList.remove('d-none');
        continuityNotConnectedDiv.classList.add('d-none');
        continuityConnectedDiv.classList.remove('d-none');

        const deviceNames = peerConnections.map(conn => conn.metadata.device);
        continuityConnectedName.textContent = deviceNames.join(', ').replace(/,([^,]*)$/, ' i$1');
        if (peerConnections.length > 1) {
            continuityIcon.icon = 'flat-color-icons:multiple-devices';
        } else {
            if (peerConnections[0].metadata.type === 'desktop') {
                continuityIcon.icon = 'fluent-emoji:desktop-computer';
            } else if (peerConnections[0].metadata.type === 'tablet') {
                continuityIcon.icon = 'flat-color-icons:tablet-android';
            } else {
                continuityIcon.icon = 'flat-color-icons:phone-android';
            }
        }
    }
    if (autoClose) {
        const modal = bootstrap.Modal.getInstance(document.getElementById('continuityModal'));
        try {
            if (modal._isShown) {
                document.getElementById('continuityModalProgress').classList.remove('d-none');
                setTimeout(() => {
                    modal.hide();
                    document.getElementById('continuityModalProgress').classList.add('d-none');
                }, 5000);
            }
        } catch (error) {

        }
    }
    document.getElementById('continuityHostBadge').classList.toggle('d-none', !isContinuityHost);
}


function gracefullyClosePeerConnection() {
    try {
        if (peer && !peer.destroyed) {
            peer.destroy(); // Gracefully close PeerJS connection
        }
    } catch (error) {
        console.error('Error closing peer connection:', error);
    }
}

window.addEventListener('beforeunload', gracefullyClosePeerConnection);
window.addEventListener('unload', gracefullyClosePeerConnection);
window.addEventListener('pagehide', gracefullyClosePeerConnection);

