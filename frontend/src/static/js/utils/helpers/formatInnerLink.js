import urlParse from 'url-parse';

export function formatInnerLink(url, baseUrl) {
  if (null === url || void 0 === url) {
    return null;
  }
  if ('string' !== typeof url) {
    try {
      url = String(url);
    } catch (e) {
      return null;
    }
  }

  let link = urlParse(url, {});

  if ('' === link.origin || 'null' === link.origin || !link.origin) {
    if (!baseUrl) {
      return link.toString();
    }
    link = urlParse(baseUrl + '/' + url.replace(/^\//g, ''), {});
  }

  return link.toString();
}
