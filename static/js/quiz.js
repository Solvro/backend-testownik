const peer = new Peer({
    config: {
        iceServers: [
            {'urls': 'stun:stun.l.google.com:19302'},
            {urls: 'turns:freeturn.tel:5349', username: 'free', credential: 'free'}
        ]
    }
});
let peerConnections = [];


peer.on('error', function (err) {
    console.error('Peer error:', err);
});

peer.on('open', function (id) {
    createContinuityQR();
});


let questions = [];
let randomizedQuestions = [];
let currentQuestionIndex = 0;
let currentQuestionData = null;
let failedQuestions = [];
let providedAnswers = 0;
let masteredQuestions = 0;
let masteredQuestionIds = [];
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

document.addEventListener('DOMContentLoaded', () => {
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
        loadMasteredQuestions();
        randomizedQuestions = shuffleArray([...questions]).filter(q => !masteredQuestionIds.includes(q.id));
        loadProgress();
        if (randomizedQuestions.length === 0) {
            document.getElementById('info').innerHTML = `
                <div class="alert alert-success alert-dismissible fade show" role="alert">
                    Gratulacje! Opanowałeś wszystkie pytania.\nZresetuj postępy aby zacząć od nowa.
                    <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
                </div>
            `;
        } else {
            loadQuestion(currentQuestionIndex);
            setInterval(updateStudyTime, 1000);
        }
        const params = new URLSearchParams(window.location.search);
        if (params.has('import')) {
            importExportData();
        }
        if (params.has('peer')) {
            const peerId = new URLSearchParams(window.location.search).get('peer');
            if (!confirm('Czy na pewno chcesz połączyć się z tym urządzeniem?')) {
                params.delete('peer');
                window.location.search = params.toString();
            }
            connectToPeer(peer, peerId).then(conn => {
                console.log('Connected to peer:', conn);
                conn.on('data', data => handlePeerData(conn, data));
                conn.on('error', error => {
                    console.error('Error connecting to peer:', error);
                });
                conn.on('close', handlePeerClose);
                conn.on('disconnected', handlePeerClose);
            }).catch(error => {
                console.error('Error connecting to peer:', error);
                alert("Nie udało się połączyć z urządzeniem. Spróbuj ponownie lub zaimportuj dane zamiast tego.");
            });
            params.delete('peer');
            window.history.replaceState({}, document.title, `${window.location.pathname}?${params.toString()}`);
        }
        if (params.has('question')) {
            const questionId = parseInt(params.get('question'), 10);
            goToQuestion(questionId);
            params.delete('question');
            window.history.replaceState({}, document.title, `${window.location.pathname}?${params.toString()}`);
        }
    });

    document.getElementById('nextButton').addEventListener('click', handleNextButtonClick);
    document.getElementById('reportButton').addEventListener('click', () => reportIncorrectQuestion(currentQuestionIndex));
    document.getElementById('resetButton').addEventListener('click', () => {
        if (confirm('Czy na pewno chcesz zresetować postępy?')) {
            resetProgress();
            window.location.reload();
        }
    });

    document.getElementById('clipboardButton').addEventListener('click', copyToClipboard);
    document.getElementById('chatGPTButton').addEventListener('click', openInChatGPT);
    document.getElementById('qrExportButton').addEventListener('click', createQRExportModal);

    document.addEventListener('keydown', handleKeyPress);
});

const fetchQuestions = async () => {
    try {
        const response = await fetch(source);
        const data = await response.json();

        questions = Array.isArray(data) ? data : data.questions || [];
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

        gtag('event', 'page_view', {
            page_title: document.title,
            page_location: window.location.href,
        });

        handleVersionUpdate();
        if (sourceProperties.report_email) {
            document.getElementById('reportButton').style.display = 'inline-block';
        }
        return true;
    } catch (error) {
        console.error('Error fetching questions:', error);
        gtag('event', 'exception', {
            description: 'Error fetching questions',
            fatal: true
        });
        gtag('event', 'page_view', {
            page_title: 'Testownik - Błąd',
            page_location: window.location.href,
        });
        return false;
    }
};

const handleVersionUpdate = () => {
    const cookies = document.cookie.split('; ');
    const versionCookie = cookies.find(row => row.startsWith(`${source}_version=`));
    const cookieVersion = versionCookie ? parseInt(versionCookie.split('=')[1]) : sourceProperties.version;

    if (!versionCookie) {
        document.cookie = `${source}_version=${sourceProperties.version};path=/;max-age=31536000`;
    }

    if (sourceProperties.version !== cookieVersion) {
        document.getElementById('info').innerHTML = `
            <div class="alert alert-success alert-dismissible fade show" role="alert">
                Baza pytań została zaktualizowana.
                <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
            </div>
        `;
        document.cookie = `${source}_version=${sourceProperties.version};path=/;max-age=31536000`;
    }
};

const shuffleArray = array => {
    for (let i = array.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [array[i], array[j]] = [array[j], array[i]];
    }
    return array;
};

const loadQuestion = (index, answersOrder = []) => {
    currentQuestionData = randomizedQuestions[index];
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
        label.className = 'btn btn-outline-secondary btn-block text-light';
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

    sendToAllPeers({
        type: 'question_loaded',
        questionId: currentQuestionData.id,
        answersOrder: currentQuestionData.answers.map(answer => answer.answer)
    });

    saveProgress();

    gtag('event', 'question_loaded', {
        'event_category': 'Question',
        'event_label': source,
        'value': currentQuestionData.id
    });
};

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
        masteredQuestions++;
        masteredQuestionIds.push(currentQuestionData.id);
        feedback.textContent = 'Poprawna odpowiedź!';
        feedback.className = 'text-success';
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
        failedQuestions.push(currentQuestionData);
    }

    if (selectedCheckboxes.length > 0) {
        providedAnswers++;
    }
    document.getElementById('providedAnswers').textContent = providedAnswers;
    document.getElementById('masteredQuestions').textContent = masteredQuestions;
    nextButton.textContent = 'Następne';
    saveProgress();
    if (!remote) {
        sendToAllPeers({
            type: 'answer_checked'
        });
    }
};

const nextQuestion = () => {
    if (currentQuestionIndex < randomizedQuestions.length - 1) {
        currentQuestionIndex++;
        loadQuestion(currentQuestionIndex);
    } else if (failedQuestions.length > 0) {
        randomizedQuestions = shuffleArray(failedQuestions);
        failedQuestions = [];
        currentQuestionIndex = 0;
        loadQuestion(currentQuestionIndex);
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
    saveProgress();
};

const saveProgress = () => {
    if (stopProgressSaving || randomizedQuestions.length === 0 || document.hidden) return;
    const progress = {
        currentQuestionId: currentQuestionData.id,
        providedAnswers,
        masteredQuestions,
        studyTime
    };
    document.cookie = `${source}_progress=${JSON.stringify(progress)};path=/;max-age=31536000`;
    document.cookie = `${source}_mastered=${JSON.stringify(masteredQuestionIds)};path=/;max-age=31536000`;
};

const loadProgress = () => {
    const cookies = document.cookie.split('; ');
    const progressCookie = cookies.find(row => row.startsWith(`${source}_progress=`));

    if (progressCookie) {
        const progress = JSON.parse(progressCookie.split('=')[1]);
        providedAnswers = progress.providedAnswers;
        masteredQuestions = progress.masteredQuestions;
        studyTime = progress.studyTime || 0;
        startTime = new Date(new Date() - studyTime * 1000);
        let foundIndex = randomizedQuestions.findIndex(q => q.id === progress.currentQuestionId);
        if (foundIndex !== -1) {
            let foundQuestion = randomizedQuestions.splice(foundIndex, 1)[0];
            randomizedQuestions.unshift(foundQuestion);
        }
    }

    document.getElementById('providedAnswers').textContent = providedAnswers;
    document.getElementById('masteredQuestions').textContent = masteredQuestions;
};

const loadMasteredQuestions = () => {
    const cookies = document.cookie.split('; ');
    const masteredCookie = cookies.find(row => row.startsWith(`${source}_mastered=`));
    if (masteredCookie) {
        masteredQuestionIds = JSON.parse(masteredCookie.split('=')[1]);
    }
};

const resetProgress = () => {
    stopProgressSaving = true;
    document.cookie = `${source}_progress=;path=/;max-age=0`;
    document.cookie = `${source}_mastered=;path=/;max-age=0`;
    document.cookie = `${source}_version=;path=/;max-age=0`;
    masteredQuestionIds = [];
};


const reportIncorrectQuestion = questionIndex => {
    const questionData = randomizedQuestions[questionIndex];
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
        failedQuestions.push(currentQuestionData);
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

const generateExportURL = () => {
    try {
        const maxQuestionId = Math.max(...masteredQuestionIds);
        const minQuestionId = Math.min(...masteredQuestionIds);

        if (maxQuestionId - minQuestionId > 999) {
            alert('Obecnie nie można eksportować pytań z tego testownka. Skontaktuj się z autorem.');
            return;
        }

        const currentUrl = new URL(window.location.href);
        const binaryMasteredQuestions = Array.from({length: maxQuestionId - minQuestionId + 1}, (_, i) => masteredQuestionIds.includes(minQuestionId + i) ? '1' : '0').join('');

        const data = {
            min: minQuestionId,
            max: maxQuestionId,
            current: currentQuestionData.id,
            studyTime: studyTime,
            providedAnswers: providedAnswers,
            mastered: binaryMasteredQuestions
        }

        return `${currentUrl.origin}${currentUrl.pathname}?import=${LZString.compressToEncodedURIComponent(JSON.stringify(data))}`;
    } catch (error) {
        console.error('Error generating export URL:', error);
        return currentUrl.href;
    }
};

const importExportData = () => {
    const params = new URLSearchParams(window.location.search);
    if (!confirm('Czy na pewno chcesz zaimportować dane? Obecne postępy na tym urządzeniu zostaną utracone.')) {
        params.delete('import');
        window.location.search = params.toString();
        return;
    }

    resetProgress();

    const importedData = JSON.parse(LZString.decompressFromEncodedURIComponent(params.get('import')));

    const minQuestionId = importedData.min;
    const maxQuestionId = importedData.max;
    const currentQuestionId = importedData.current;
    studyTime = importedData.studyTime;
    providedAnswers = importedData.providedAnswers;
    const binaryMasteredQuestions = importedData.mastered;
    masteredQuestionIds = Array.from({length: maxQuestionId - minQuestionId + 1}, (_, i) => binaryMasteredQuestions[i] === '1' ? minQuestionId + i : null).filter(id => id !== null);

    const progress = {
        currentQuestionId,
        providedAnswers,
        masteredQuestions: masteredQuestionIds.length,
        studyTime
    };
    document.cookie = `${source}_progress=${JSON.stringify(progress)};path=/;max-age=31536000`;
    document.cookie = `${source}_mastered=${JSON.stringify(masteredQuestionIds)};path=/;max-age=31536000`;

    params.delete('import');
    window.location.search = params.toString();
};

const createQRExportModal = () => {
    const modal = new bootstrap.Modal(document.getElementById('qrExportModal'));
    const qrCodeElement = document.getElementById('exportQRCode');
    qrCodeElement.innerHTML = '';
    new QRCode(qrCodeElement, {
        text: generateExportURL(),
        width: 512,
        height: 512,
        colorDark: '#000000',
        colorLight: '#ffffff',
        correctLevel: QRCode.CorrectLevel.H
    });

    modal.show();
};

const goToQuestion = (questionId, answersOrder = []) => {
    const foundIndex = randomizedQuestions.findIndex(q => q.id === questionId);
    if (foundIndex !== -1) {
        randomizedQuestions.splice(foundIndex, 1);
        randomizedQuestions.unshift(questions.find(q => q.id === questionId));
        currentQuestionIndex = 0;
        loadQuestion(currentQuestionIndex, answersOrder);
        if (masteredQuestionIds.includes(questionId)) {
            masteredQuestions--;
            document.getElementById('masteredQuestions').textContent = masteredQuestions;
            masteredQuestionIds = masteredQuestionIds.filter(q => q !== questionId);
        }
    } else {
        if (masteredQuestionIds.includes(questionId)) {
            randomizedQuestions.splice(currentQuestionIndex + 1, 0, questions.find(q => q.id === questionId));
            masteredQuestionIds = masteredQuestionIds.filter(q => q.id !== questionId);
            masteredQuestions--;
            document.getElementById('masteredQuestions').textContent = masteredQuestions;
            saveProgress();
            goToQuestion(questionId, answersOrder);
        } else {
            console.error(`Question with ID ${questionId} not found.`);
        }
    }
}


// Continuity

const createContinuityQR = () => {
    const qrCodeElement = document.getElementById('continuityQRCode');
    const currentUrl = new URL(window.location.href);
    getPeerId().then(peerId => {
        qrCodeElement.innerHTML = '';
        new QRCode(qrCodeElement, {
            text: `${currentUrl.origin}${currentUrl.pathname}?peer=${peerId}`,
            colorDark: '#000000',
            colorLight: '#ffffff',
            correctLevel: QRCode.CorrectLevel.H
        });

    });
};


const handlePeerConnection = (conn) => {
    console.log('Connection established:', conn);
    peerConnections.push(conn);
    updateContinuityModal(false, true);
    conn.on('data', data => handlePeerData(conn, data));
    conn.on('error', function (err) {
        console.error('Connection error:', err);
    });
    conn.on('close', handlePeerClose);
    conn.on('disconnected', handlePeerClose);
    conn.on('open', function () {
        sendToPeer(conn, {
            type: 'progress_sync',
            studyTime,
            providedAnswers,
            mastered: masteredQuestionIds
        });
        sendToPeer(conn, {
            type: 'question_loaded',
            questionId: currentQuestionData.id,
            answersOrder: currentQuestionData.answers.map(answer => answer.answer)
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

peer.on('connection', handlePeerConnection);

const handlePeerClose = (conn) => {
    console.log('Connection closed:', conn);
    peerConnections = peerConnections.filter(c => c.open);
    updateContinuityModal();
    bootstrap.Toast.getOrCreateInstance(document.getElementById('continuityDisconnectedToast')).show();
}

const handlePeerData = (conn, data) => {
    console.log('Received data from peer:', data);
    sendToAllPeersExcept(conn, data);
    switch (data.type) {
        case 'progress_sync':
            studyTime = data.studyTime;
            startTime = new Date(new Date() - studyTime * 1000);
            providedAnswers = data.providedAnswers;
            masteredQuestionIds = data.mastered;
            masteredQuestions = masteredQuestionIds.length;
            document.getElementById('masteredQuestions').textContent = masteredQuestions;
            document.getElementById('providedAnswers').textContent = providedAnswers;
            saveProgress();
            break;
        case 'question_loaded':
            if (currentQuestionData && currentQuestionData.id === data.questionId) {
                if (data.answersOrder.length > 0) {
                    if (currentQuestionData.answers.map(answer => answer.answer).join(',') !== data.answersOrder.join(',')) {
                        loadQuestion(currentQuestionIndex, data.answersOrder);
                    }
                }
                return;
            }
            goToQuestion(data.questionId, data.answersOrder);
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

const connectToPeer = (peer, peerId) => {
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

const updateContinuityModal = (forceQR = false, autoClose = false) => {
    const continuityQRDiv = document.getElementById('continuityQRDiv');
    const continuityConnectedDiv = document.getElementById('continuityConnectedDiv');
    const continuityConnectedName = document.getElementById('continuityConnectedName');
    const continuityIcon = document.getElementById('continuityIcon');

    if (peerConnections.length === 0 || forceQR) {
        createContinuityQR();
        continuityQRDiv.classList.remove('d-none');
        continuityConnectedDiv.classList.add('d-none');
        if (peerConnections.length === 0) {
            continuityIcon.icon = 'flat-color-icons:multiple-devices';
        }
    } else {
        continuityQRDiv.classList.add('d-none');
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
}

document.getElementById('continuityConnectMoreButton').addEventListener('click', () => {
    createContinuityQR();
    updateContinuityModal(true);
});