from urllib.parse import urljoin
import re
import logging

import requests_cache
from bs4 import BeautifulSoup
from tqdm import tqdm

from constants import BASE_DIR, MAIN_DOC_URL, PEP_URL, EXPECTED_STATUS
from configs import configure_argument_parser, configure_logging
from outputs import control_output
from utils import get_response, find_tag


def whats_new(session):
    whats_new_url = urljoin(MAIN_DOC_URL, 'whatsnew/')
    '''response = session.get(whats_new_url)
    response.encoding = 'utf-8'''

    response = get_response(session, whats_new_url)
    if response is None:
        return

    soup = BeautifulSoup(response.text, features='lxml')

    # main_div = soup.find('section', attrs={'id': 'what-s-new-in-python'})
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
        h1 = find_tag(soup, 'h1')  # Найдите в "супе" тег h1.
        dl = find_tag(soup, 'dl')  # Найдите в "супе" тег dl.
        dl_text = dl.text.replace('\n', ' ')
        results.append((version_link, h1.text, dl_text))
    return results


def latest_versions(session):
    # session = requests_cache.CachedSession()
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

    response = session.get(archive_url)

    with open(archive_path, 'wb') as file:
        file.write(response.content)
    logging.info(f'Архив был загружен и сохранён: {archive_path}')


def check_status_mismatch(inform, type_on_page, status_on_page, link, diff):
    """Поиск несоответствий статусов"""
    page_inform = type_on_page + status_on_page

    if len(inform) == 1:
        if inform != type_on_page:
            diff.append((inform, page_inform, link))
    elif len(inform) == 2:
        if inform != page_inform:
            diff.append((inform, page_inform, link))


def find_status_type(dt_all):
    """Посик на страницах каждого статуса и типа"""
    type_on_page = "?"
    status_on_page = "?"
    for dt in dt_all:
        if dt.text == 'Type:':
            type_on_page = dt.find_next_sibling('dd')
            type_on_page = find_tag(type_on_page, 'abbr').text[0]
        elif dt.text == 'Status:':
            status_on_page = dt.find_next_sibling('dd')
            status_on_page = find_tag(status_on_page, 'abbr').text[0]
    return type_on_page, status_on_page


def pep(session):
    response = get_response(session, PEP_URL)
    if response is None:
        return

    soup = BeautifulSoup(response.text, features='lxml')
    tables = soup.find_all('table', attrs={
        'class': 'pep-zero-table docutils align-default'})
    diff = []
    results = [('Статус', 'Количество')]
    status_count = {}
    for table in tqdm(tables):
        table_body = find_tag(table, 'tbody')
        lines = table_body.find_all('tr')
        for line in lines:
            short_link = find_tag(line,
                                  'a',
                                  {'class': 'pep reference internal'})['href']
            link = urljoin(PEP_URL, short_link)
            abbr_tag = line.find('abbr')
            if abbr_tag is None:
                continue
            inform = abbr_tag.text

            response = get_response(session, link)
            if response is None:
                return
            soup = BeautifulSoup(response.text, features='lxml')

            dt_all = soup.find_all('dt')
            type_on_page, status_on_page = find_status_type(dt_all)

            check_status_mismatch(inform, type_on_page,
                                  status_on_page, link, diff)

            if status_on_page in status_count:
                status_count[status_on_page] += 1
            else:
                status_count[status_on_page] = 1

    peps = 0
    for status in status_count.keys():
        results.append((EXPECTED_STATUS[status], status_count[status]))
        peps += status_count[status]
    results.append(('Total', peps))

    logging.info('Несовпадающие статусы:')
    for inf, page_inf, link in diff:
        logging.info(link)
        logging.info(f'Статус в карточке: {page_inf}')
        logging.info(f'Ожидаемые статусы: {inf}')

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
