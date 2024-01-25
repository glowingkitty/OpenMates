let letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('');
for (let i = 0; i < 3; i++) {
    for (let j = 0; j < 26; j++) {
        letters.push(String.fromCharCode(65 + i) + String.fromCharCode(65 + j));
    }
}

let counter = 0;
let letterIndex = 0;

document.querySelectorAll('a, form, button').forEach((element, index) => {
    let rect = element.getBoundingClientRect();
    let inView = rect.top >= 0 && rect.bottom <= window.innerHeight;

    if (inView) {
        let outerDiv = document.createElement('div');
        outerDiv.style.border = '2px solid red';
        outerDiv.style.margin = '2px';
        outerDiv.style.display = 'flex';
        outerDiv.style.alignItems = 'stretch';
        outerDiv.style.justifyContent = 'space-between';

        let innerDiv = document.createElement('div');
        innerDiv.style.backgroundColor = 'red';
        innerDiv.style.color = 'white';
        innerDiv.style.fontFamily = 'Arial';
        innerDiv.style.fontSize = '15px'; 
        innerDiv.style.fontWeight = 'bold';
        innerDiv.style.padding = '1px';
        innerDiv.style.lineHeight = '1.5';
        innerDiv.style.height = '100%';

        if (counter === 3) {
            counter = 0;
            letterIndex++;
            if (letterIndex === letters.length) {
                letterIndex = 0;
            }
        }
        let id = letters[letterIndex] + (counter + 1);
        innerDiv.appendChild(document.createTextNode(id));

        outerDiv.appendChild(innerDiv);

        let elementDiv = document.createElement('div');
        elementDiv.appendChild(element.cloneNode(true));
        outerDiv.appendChild(elementDiv);

        let borderDiv = document.createElement('div');
        borderDiv.style.border = '4px solid white';
        borderDiv.appendChild(outerDiv);

        element.replaceWith(borderDiv);
        counter++;
    }
});