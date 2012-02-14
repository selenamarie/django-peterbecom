import jinja2
from jingo import register
from django.template.loader import render_to_string
from .models import BlogItem, BlogComment, Category


@register.function
def show_comments(parent, user):
    if parent.__class__ == BlogItem:
        filter_ = {'blogitem': parent, 'parent': None}
    else:
        filter_ = {'parent': parent}
    if not user.is_staff:
        filter_['approved'] = True
    html = []
    for comment in (BlogComment.objects
                    .filter(**filter_)
                    .order_by('add_date')):
        html.append(render_to_string('plog/comment.html', {
          'comment': comment,
          'preview': False,
          'user': user,
        }))
    return '\n'.join(html)


@register.function
def line_indent(text):
    print "WORK HARDER ON THIS"
    print repr(text)
    return text
