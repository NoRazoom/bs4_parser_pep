from urllib.parse import urljoin
import re
import logging
from collections import defaultdict

import requests_cache
from bs4 import BeautifulSoup
from tqdm import tqdm

from constants import BASE_DIR, MAIN_DOC_URL, PEP_URL, EXPECTED_STATUS
from configs import configure_argument_parser, configure_logging
from outputs import control_output
from utils import get_response, find_tag


def whats_new(session):
    whats_new_url = urljoin(MAIN_DOC_URL, 'whatsnew/')

    response = get_response(session, whats_new_url)
    if response is None:
        return

    soup = BeautifulSoup(response.text, features='lxml')
    main_div = find_tag(soup, 'section', attrs={'id': 'what-s-new-in-python'})

    div_with_ul = find_tag(main_div, 'div', attrs={'class': 'toctree-wrapper'})

    sections_by_python = div_with_ul.find_all('li',
                                              attrs={'class': 'toctree-l1'})

    results = [('Ссылка на статью', 'Заголовок', 'Редактор, автор')]
    for section in tqdm(sections_by_python):
        version_a_tag = find_tag(section, 'a')
        href = version_a_tag['href']
        version_link = urljoin(whats_new_url, href)
        response = get_response(session, version_link)
        if response is None:
            continue
        soup = BeautifulSoup(response.text, features='lxml')
        h1 = find_tag(soup, 'h1')
        dl = find_tag(soup, 'dl')
        dl_text = dl.text.replace('\n', ' ')
        results.append((version_link, h1.text, dl_text))
    return results


def latest_versions(session):
    response = get_response(session, MAIN_DOC_URL)
    if response is None:
        return

    soup = BeautifulSoup(response.text, features='lxml')
    sidebar = find_tag(soup, 'div', {'class': 'sphinxsidebarwrapper'})
    ul_tags = sidebar.find_all('ul')

    # Перебор в цикле всех найденных списков.
    for ul in ul_tags:
        # Проверка, есть ли искомый текст в содержимом тега.
        if 'All versions' in ul.text:
            # Если текст найден, ищутся все теги <a> в этом списке.
            a_tags = ul.find_all('a')
            # Остановка перебора списков.
            break
    # Если нужный список не нашёлся,
    # вызывается исключение и выполнение программы прерывается.
    else:
        raise Exception('Ничего не нашлось')

    results = [('Ссылка на документацию', 'Версия', 'Статус')]
    # Шаблон для поиска версии и статуса:
    pattern = r'Python (?P<version>\d\.\d+) \((?P<status>.*)\)'

    for a in a_tags:
        link = a['href']
        text_match = re.search(pattern, a.text)
        if text_match is not None:
            # Если строка соответствует паттерну,
            # переменным присываивается содержимое групп, начиная с первой.
            version, status = text_match.groups()
        else:
            version, status = a.text, ''
        results.append((link, status, version))

    return results


def download(session):
    # Вместо константы DOWNLOADS_URL, используйте переменную downloads_url.
    downloads_url = urljoin(MAIN_DOC_URL, 'download.html')

    # session = requests_cache.CachedSession()
    response = get_response(session, downloads_url)
    if response is None:
        return

    soup = BeautifulSoup(response.text, features='lxml')
    table = find_tag(soup, 'table', attrs={'class': 'docutils'})
    text_dow = find_tag(table, 'a', {'href': re.compile(r'.+docs-text\.zip$')})
    link = text_dow['href']
    archive_url = urljoin(downloads_url, link)

    filename = archive_url.split('/')[-1]
    downloads_dir = BASE_DIR / 'downloads'
    downloads_dir.mkdir(exist_ok=True)
    archive_path = downloads_dir / filename

    response = get_response(session, archive_url)
    if response is None:
        return

    with open(archive_path, 'wb') as file:
        file.write(response.content)
    logging.info(f'Архив был загружен и сохранён: {archive_path}')


def pep(session):
    response = get_response(session, PEP_URL)
    if response is None:
        return

    soup = BeautifulSoup(response.text, features='lxml')
    lines = soup.find_all('a', attrs={'class': 'pep reference internal'})
    diff = []
    results = [('Статус', 'Количество')]
    status_count = defaultdict(int)
    for link in tqdm(lines):
        parent_td = link.find_parent('td')  # второй тд
        parent_tr = parent_td.find_parent('tr') if parent_td else None
        status_td = parent_tr.find('td') if parent_tr else None  # первый тд
        preview_status = ""
        if status_td:
            preview_status = status_td.text[1:]
        expected_statuses = EXPECTED_STATUS[preview_status]
        pep_link = urljoin(PEP_URL, link['href'])
        pep_response = get_response(session, pep_link)
        soup = BeautifulSoup(pep_response.text, features='lxml')
        section = find_tag(soup, 'section', {'id': 'pep-content'})
        table = find_tag(section, 'dl', {'class': 'field-list'})

        status_row = table.find(string='Status').parent
        status_tag = status_row.find_next_sibling('dd')
        status = status_tag.string
        if status not in expected_statuses:
            diff.append(
                f'{pep_link}\nСтатус в карточке: {status}\n'
                f'Ожидаемые статусы: {expected_statuses}'
            )

        status_count[EXPECTED_STATUS[preview_status]] += 1

    results.extend(status_count.items())
    peps = sum(status_count.values())
    results.append(('Total', peps))

    logging.info('Несовпадающие статусы:')
    for message in diff:
        logging.info(message)

    return results


MODE_TO_FUNCTION = {
    'whats-new': whats_new,
    'latest-versions': latest_versions,
    'download': download,
    'pep': pep,
}


def main():
    configure_logging()
    logging.info('Парсер запущен!')

    # Конфигурация парсера аргументов командной строки —
    # передача в функцию допустимых вариантов выбора.
    arg_parser = configure_argument_parser(MODE_TO_FUNCTION.keys())
    # Считывание аргументов из командной строки.
    args = arg_parser.parse_args()
    logging.info(f'Аргументы командной строки: {args}')

    session = requests_cache.CachedSession()
    # Если был передан ключ '--clear-cache', то args.clear_cache == True.
    if args.clear_cache:
        # Очистка кеша.
        session.cache.clear()

    # Получение из аргументов командной строки нужного режима работы.
    parser_mode = args.mode
    # Поиск и вызов нужной функции по ключу словаря.
    results = MODE_TO_FUNCTION[parser_mode](session)

    # Если из функции вернулись какие-то результаты,
    if results is not None:
        # передаём их в функцию вывода вместе с аргументами командной строки.
        control_output(results, args)
    logging.info('Парсер завершил работу.')


if __name__ == '__main__':
    main()
