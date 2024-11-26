// Function to fetch grades data
async function fetchData() {
    try {
        const response = await fetch('/api/get-grades/');
        return await response.json();
    } catch (error) {
        console.error('Error fetching grades:', error);
        return [];
    }
}

// Function to calculate average grade
function calculateAverage(courses) {
    const sum = courses.reduce((acc, course) => {
        const courseSum = course.grades.reduce((courseAcc, grade) =>
            courseAcc + (!grade.counts_into_average ? 0 : grade.value * course.ects), 0);
        return acc + courseSum;
    }, 0);

    const totalWeight = courses.reduce((acc, course) => {
        const courseWeight = course.grades.reduce((courseAcc, grade) =>
            courseAcc + (!grade.counts_into_average ? 0 : course.ects), 0);
        return acc + courseWeight;
    }, 0);

    return (sum / totalWeight).toFixed(2);
}

// Function to render grades
function renderGrades(courses) {
    const table_body = document.getElementById('grades');
    table_body.innerHTML = '';

    courses.forEach(course => {
        const gradeElement = document.createElement('tr');
        let statusClass = '';
        if (course.passing_status === 'passed') {
            statusClass = 'has-text-success';
        } else if (course.passing_status === 'failed') {
            statusClass = 'has-text-danger';
        } else if (course.passing_status === 'not_yet_passed') {
            statusClass = '';
        }
        gradeElement.innerHTML = `
            <td>${course.course_name}</td>
            <td>${course.ects}</td>
            <td class='${statusClass}'>${course.grades.map(grade => grade.value_symbol).join('; ') || '-'}</td>
        `;
        table_body.appendChild(gradeElement);
    });

    const average = calculateAverage(courses);
    document.getElementById('average').innerText = average === "NaN" ? "-" : average;
}

// Function to populate term-select dropdown
function populateTermSelect(terms) {
    const today = new Date();
    const termSelect = document.getElementById('term-select');
    termSelect.parentElement.classList.remove('is-loading');
    termSelect.innerHTML = '';
    terms.forEach(term => {
        const option = document.createElement('option');
        option.value = term.id;
        option.text = term.name;
        if (today >= new Date(term.start_date) && today <= new Date(term.end_date)) {
            option.selected = true;
        }
        termSelect.appendChild(option);
    });
}

// Main function to fetch and render grades and populate terms
async function main() {
    let data = await fetchData();
    let courses = data.courses;

    populateTermSelect(data.terms);

    const termSelect = document.getElementById('term-select');
    let selectedTerm = termSelect.value;
    let filteredCourses = selectedTerm ? courses.filter(course => course.term_id === selectedTerm) : courses;
    renderGrades(filteredCourses);

    // Add event listener to term-select to filter grades
    termSelect.addEventListener('change', () => {
        const selectedTerm = termSelect.value;
        const filteredCourses = selectedTerm ? courses.filter(course => course.term_id === selectedTerm) : courses;
        renderGrades(filteredCourses);
    });
}

// Execute main function on page load
window.onload = main;
