const trueFalseStrings = {
    "prawda": true, "tak": true, "true": true,
    "fałsz": false, "nie": false, "false": false
};

let questions = [];
let questionSet = new Set();
let index = 1;

document.addEventListener('DOMContentLoaded', () => {
    const fileInput = document.getElementById('file-input');
    const fileBox = document.getElementById('file-box');

    fileInput.addEventListener('change', handleFileSelect);
    fileBox.addEventListener('dragover', handleDragOver);
    fileBox.addEventListener('dragleave', handleDragLeave);
    fileBox.addEventListener('drop', handleFileDrop);

    const directoryInput = document.getElementById('directory-input');
    const directoryBox = document.getElementById('directory-box');

    directoryInput.addEventListener('change', handleFolderSelect);
    directoryBox.addEventListener('dragover', handleDragOver);
    directoryBox.addEventListener('dragleave', handleDragLeave);
    directoryBox.addEventListener('drop', handleFolderDrop);

    document.getElementById('import-button').addEventListener('click', async () => {
        let data
        try {
            data = await importQuiz()
        } catch (error) {
            showError('import-error', error.message);
            return;
        }
        fetch('/quizzes/import/',
            {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: JSON.stringify(data)
            }
        ).then(response => {
            if (response.ok) {
                response.json().then(data =>
                    window.location.href = `/quizzes/${data.id}/`
                );
            } else {
                response.json().then(data => {
                    showError('import-error', data.error);
                });
            }
        });

    });

    function handleFileSelect(evt) {
        const file = evt.target.files[0];
        const name = document.getElementById('file-name');
        if (file) {
            document.getElementById('file-box').classList.add('has-name');
            name.textContent = file.name;
            name.style.display = 'inline';
            directoryInput.value = '';
            const directoryName = document.getElementById('directory-name');
            directoryName.textContent = '';
            directoryName.style.display = 'none';
        } else {
            document.getElementById('file-box').classList.remove('has-name');
            name.style.display = 'none';
        }
        handleDragLeave();
    }

    function handleFolderSelect(evt) {
        const files = evt.target.files;
        const directoryPath = files[0].webkitRelativePath;
        const directoryName = directoryPath.split('/')[0];
        const name = document.getElementById('directory-name');
        if (files) {
            document.getElementById('directory-box').classList.add('has-name');
            name.textContent = directoryName;
            name.style.display = 'inline';
            fileInput.value = '';
            const fileName = document.getElementById('file-name');
            fileName.textContent = '';
            fileName.style.display = 'none';
            document.getElementById('file-box').classList.remove('has-name');
        } else {
            document.getElementById('directory-box').classList.remove('has-name');
            name.style.display = 'none';
        }
        handleDragLeave();
    }

    function handleFileDrop(evt) {
        evt.preventDefault();
        evt.stopPropagation();
        const file = evt.dataTransfer.files[0];
        if (file) {
            fileInput.files = evt.dataTransfer.files;
            handleFileSelect({target: {files: [file]}});
        }
    }

    function handleFolderDrop(evt) {
        evt.preventDefault();
        evt.stopPropagation();
        const directory = evt.dataTransfer.files[0];
        if (directory) {
            directoryInput.files = evt.dataTransfer.files;
            handleFolderSelect({target: {files: [directory]}});
        }
    }

    function handleDragOver(evt, uploadType) {
        evt.preventDefault();
        evt.stopPropagation();
        if (evt.dataTransfer.items && evt.dataTransfer.items.length === 1 && evt.dataTransfer.items[0].kind === uploadType) {
            evt.dataTransfer.dropEffect = 'copy';
            if (document.getElementById(`${uploadType}-name`).style.display === 'none') {
                document.querySelector('.file-cta').classList.add('dragover');
            } else {
                fileBox.classList.add('dragover');
            }
        } else {
            evt.dataTransfer.dropEffect = 'none';
        }
    }

    function handleDragLeave(evt) {
        if (evt) {
            evt.preventDefault();
            evt.stopPropagation();
        }
        fileBox.classList.remove('dragover');
        document.querySelector('.file-cta').classList.remove('dragover');
    }

    async function importQuiz() {
        let title = document.getElementById('title').value;
        if (title === '') {
            throw new Error('Nie podano nazwy bazy.');
        }
        await processFiles();
        return {
            "type": "json",
            "data": {
                "title": title,
                "description": document.getElementById('description').value || null,
                "questions": questions
            }
        };
    }

    function showError(id, message) {
        const help = document.getElementById(id);
        help.textContent = message;
        help.style.display = 'block';
        help.classList.add('is-danger');
    }

    async function processFiles() {
        const directoryInput = document.getElementById('directory-input');
        const zipInput = document.getElementById('file-input');

        if (directoryInput.files.length > 0) {
            await processDirectory(directoryInput.files);
        } else if (zipInput.files.length > 0) {
            await processZip(zipInput.files[0]);
        } else {
            throw new Error('Nie wybrano pliku ani folderu.');
        }
    }


    async function processDirectory(files) {
        for (const file of files) {
            if (file.name.endsWith('.txt')) {
                const lines = await readFile(file);
                await processQuestion(lines, file.name);
            }
        }
    }

    async function processZip(file) {
        const zip = await JSZip.loadAsync(file);
        for (const file in zip.files) {
            if (file.endsWith('.txt')) {
                const content = await zip.file(file).async('string');
                const lines = content.split('\n').map(line => line.trim());
                await processQuestion(lines, file);
            }
        }
    }

    async function readFile(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result.split('\n').map(line => line.trim()));
            reader.onerror = reject;
            reader.readAsText(file);
        });
    }

    async function processQuestion(lines, path) {
        const template = lines[0].trim();
        const question = lines[1].trim();
        const answers = [];

        for (let s = 2; s < lines.length; s++) {
            try {
                answers.push({
                    "answer": lines[s].trim(),
                    "correct": template[s - 1] === '1'
                });
            } catch (error) {
                console.error(`Error in file ${path} at line ${s}. Replacing the unknown value with False.`);
                answers.push({
                    "answer": lines[s].trim(),
                    "correct": false
                });
            }
        }

        const isTrueFalse = (template === "X01" || template === "X10") &&
            trueFalseStrings[answers[0].answer.toLowerCase()] !== undefined &&
            trueFalseStrings[answers[1].answer.toLowerCase()] !== undefined;

        const questionObj = {
            "question": question,
            "answers": answers,
            "multiple": !isTrueFalse,
            "explanation": null,
            "id": index++
        };

        const questionStr = JSON.stringify({
            "question": questionObj.question,
            "answers": answers.sort((a, b) => a.answer.localeCompare(b.answer))
        }).toLowerCase();

        if (!questionSet.has(questionStr)) {
            questions.push(questionObj);
            questionSet.add(questionStr);
        } else {
            console.log(`Duplicate question in file ${path}. Skipping.`);
        }
    }

});