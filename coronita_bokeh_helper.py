import pandas as pd
import numpy as np
from collections import OrderedDict
import io

from bokeh.plotting import figure, show
from bokeh.io import reset_output, output_notebook, curdoc, output_file, save
from bokeh.themes import built_in_themes
from bokeh.layouts import row, column, grid
from bokeh.models import ColumnDataSource, NumeralTickFormatter, HoverTool, Label, LinearAxis, Range1d, \
    Span, DatetimeTickFormatter, CustomJS, Select, Button, Patch, Legend, Div
from bokeh.embed import components
from bokeh.resources import INLINE

from jinja2 import Template

bk_theme = 'dark_minimal'

def add_bokeh_footnote(p):
    msg1 = 'www.COVIDoutlook.info | twtr: @COVIDoutlook'
    msg2 = 'Chart created on {}'.format(pd.Timestamp.today().strftime("%d %b %Y"))

    label_opts = dict(
        x=0, y=0,
        x_units='screen', y_units='screen',
        text_font_size='100%',
        text_color='white'
    )

    caption1 = Label(text=msg1, **label_opts)
    caption2 = Label(text=msg2, **label_opts)
    p.add_layout(caption1, 'below')
    p.add_layout(caption2, 'below')
    return p

def bk_legend(p, location='default', font_size=100):
    p.legend.title = 'Interactive Legend'
    p.legend.title_text_font_style = "bold"
    p.legend.title_text_font_size = str(font_size)+'%'
    p.legend.title_text_color = "white"
    p.legend.label_text_font_size = str(font_size*0.75)+'%'
    p.legend.glyph_height = 10
    p.legend.label_height = 0
    p.legend.glyph_width = 10
    p.legend.spacing = 15
    p.legend.padding = 5
    p.legend.background_fill_alpha = 0.9
    p.legend.click_policy = "hide"

    # if location != 'default':
        # p.legend.location = location

    return p

def bk_overview_layout(p, num_in_row=1, min_height=360):
    p.legend.location = 'center'
    p.legend.orientation = 'horizontal'
    p.add_layout(p.legend[0], 'above')
    p.title.text_font_size = '100%'
    p.title.align = 'left'
    p.yaxis.axis_label_text_font_size = '100%'
    p.yaxis.major_label_text_font_size = '80%'
    if num_in_row > 1:
        p.plot_height = min_height
        p.plot_width = p.plot_height
        # p.sizing_mode = 'scale_height'
    else:
        p.plot_width = int(min_height*5/3)
        p.plot_height = min_height
        # p.sizing_mode = 'scale_width'

    #Possible values are "fixed", "scale_width", "scale_height", "scale_both", and "stretch_both"

    return p

def bk_add_event_lines(p, df_int):
    # df_int = df_interventions[df_interventions.state_code.isin([state, 'US'])].groupby('dt').first().reset_index()
    for thisidx in df_int.index:
        if df_int.loc[thisidx, 'social_distancing_direction'] == 'holiday':
            thislinecolor = '#8900a5'
        elif df_int.loc[thisidx, 'social_distancing_direction'] == 'restricting':
            thislinecolor = '#973200'
        elif df_int.loc[thisidx, 'social_distancing_direction'] == 'easing':
            thislinecolor = '#178400'
        p.add_layout(Span(location=df_int.loc[thisidx, 'dt'],
                          dimension='height',
                          line_color='black', #thislinecolor,
                          line_dash='solid',
                          line_alpha=.3,
                          line_width=2
                          )
                     )
    return p

def bk_bar_and_line_chart(bar_series, bar_name='bar', bar_color='#008fd5',
                          line_series=False, line_name='line', line_color='#fc4f30',
                          chart_title='', yformat='{:.1%}',
                          bar2_series=None, bar2_name='bar2', bar2_color='#e5ae38'):

    p = figure(title=chart_title, x_axis_type="datetime",
               tools='pan,wheel_zoom,box_zoom,zoom_in,zoom_out,reset,save')

    p.yaxis.formatter = NumeralTickFormatter(format="0a")

    if isinstance(bar2_series, pd.Series):
        source = pd.concat([line_series, bar2_series, bar_series], axis=1).reset_index()
        source.columns = ['dt', line_name, bar2_name, bar_name]
        p.vbar_stack(stackers=[bar2_name, bar_name],
                     x='dt',
                     color=[bar2_color, bar_color],
                     source=source, width=pd.Timedelta(days=1) * .5,
                     legend_label=[bar2_name, bar_name],
                     name=[bar2_name, bar_name]
                     )
    else:
        source = pd.concat([line_series, bar_series], axis=1).reset_index()
        source.columns = ['dt', line_name, bar_name]
        p.vbar(x='dt', top=bar_name,
               source=source, color=bar_color, width=pd.Timedelta(days=1) * .5,
               legend_label=bar_name,
               name=bar_name
               )

    p.line(x='dt', y=line_name, source=source, color=line_color, width=4, legend_label=line_name, name=line_name)

    p.toolbar.autohide = True
    bk_legend(p, 'top_left')

    p.add_tools(HoverTool(
        tooltips=[
            ('Date', '@dt{%F}'),
            ('Name', '$name'),
            ('Value', '@$name{0,0}')
        ],
        formatters={'@dt': 'datetime'}
    ))

    p = add_bokeh_footnote(p)

    return p

def bk_rt_confid(model_dict, param_str, chart_title=""):
    df_rt = model_dict['df_rts_conf'][['weighted_average']].unstack('metric')
    rt_name = df_rt.columns.levels[0][0]
    df_rt = df_rt[rt_name].dropna(how='all').reset_index()

    p = figure(title='{}: Reproduction Rate (Rᵗ) Estimate - {}'.format(model_dict['region_name'], chart_title),
               x_axis_type="datetime",
               tools='pan,wheel_zoom,box_zoom,zoom_in,zoom_out,reset,save')

    p.line(x='dt', y='rt', source=df_rt, color='#008FD5', width=4,
           legend_label='Reproduction Rate, Rᵗ', level='overlay')

    patch = p.varea(x='dt', y1='rt_l68', y2='rt_u68', source=df_rt,
                    color='#E39D22', alpha=0.75, legend_label='68% Confidence Interval', level='glyph')

    patch2 = p.varea(x='dt', y1='rt_l95', y2='rt_u95', source=df_rt,
                     color='#E39D22', alpha=0.25, legend_label='95% Confidence Interval', level='glyph')

    bg_upper = p.varea(x=[df_rt.dt.min(), df_rt.dt.max()],
                       y1=[1.0, 1.0], y2=[df_rt.rt_u95.max(), df_rt.rt_u95.max()],
                       color='red', level='underlay', alpha=0.15
                       )
    bg_lower = p.varea(x=[df_rt.dt.min(), df_rt.dt.max()],
                       y1=[0, 0], y2=[1.0, 1.0],
                       color='blue', level='underlay', alpha=0.15
                       )

    p.add_layout(Span(location=1.0,
                      dimension='width',
                      line_color='white',  # thislinecolor,
                      line_dash='dashed',
                      line_alpha=.7,
                      line_width=2
                      )
                 )

    p.add_layout(Label(
        x=df_rt.dt.mean(), y=1.5, y_units='data', text='Rᵗ > 1: Epidemic Worsening',
        text_color='white', text_alpha=0.4, text_font_size='150%', text_align='center'))
    p.add_layout(Label(
        x=df_rt.dt.mean(), y=0.1, y_units='data', text='Rᵗ < 1: Epidemic Improving',
        text_color='white', text_alpha=0.4, text_font_size='150%', text_align='center'))

    p.toolbar.autohide = True
    bk_legend(p, 'top_center')

    p.add_tools(HoverTool(
        tooltips=[
            ('Date', '@dt{%F}'),
            ('Reproduction Rate, Rᵗ', '@rt{0.00}'),
            ('68% Confidence Interval', '@rt_l68{0.00} - @rt_u68{0.00}'),
            ('95% Confidence Interval', '@rt_l95{0.00} - @rt_u95{0.00}')
        ],
        formatters={'@dt': 'datetime'},
        mode='vline'
    ))

    p.y_range = Range1d(0, df_rt.rt_u68.max())
    p.extra_y_ranges = {"foo": p.y_range}

    # Adding the second axis to the plot.
    p.add_layout(LinearAxis(y_range_name="foo", axis_label=p.yaxis.axis_label,
                            formatter=p.yaxis.formatter), 'right')

    p = add_bokeh_footnote(p)

    return p

def bk_population_share(df_agg, model_dict, param_str, chart_title=""):
    col_names = ['susceptible', 'deaths', 'exposed', 'infectious', 'hospitalized', 'recovered']
    legend_names = ['Susceptible', 'Deaths', 'Exposed',
                    'Infectious', 'Hospitalizations', 'Recoveries']
    df_chart = df_agg[col_names].dropna(how='all')
    df_chart = df_chart.clip(lower=0)
    df_chart = df_chart.iloc[8:].reset_index()

    p = figure(title='{}: Population Overview Forecast - {}'.format(model_dict['region_name'], chart_title),
               x_axis_type="datetime",
               tools='pan,wheel_zoom,box_zoom,zoom_in,zoom_out,reset,save')

    p.varea_stack(col_names,
                  x='dt', source=df_chart,
                  color=['#008fd5', '#fc4f30', '#e5ae38', '#6d904f', '#8b8b8b', '#810f7c'],
                  legend_label=legend_names
                  )

    p.vline_stack('susceptible',
                  x='dt', source=df_chart,
                  width=0
                  )
    p.legend.location = "bottom_left"
    p.legend.click_policy = "hide"
    p.toolbar.autohide = True
    p.y_range = Range1d(0, df_chart.sum(axis=1).max())
    p.yaxis.formatter = NumeralTickFormatter(format="0a")
    p.yaxis.axis_label = 'Population'
    p.yaxis.major_tick_out = 5
    p.yaxis.major_tick_line_alpha = .9
    p.yaxis.minor_tick_in = 4
    p.yaxis.minor_tick_line_alpha = .9

    # Setting the second y axis range name and range
    p.extra_y_ranges = {"foo": Range1d(start=0, end=1)}

    # Adding the second axis to the plot.
    p.add_layout(LinearAxis(y_range_name="foo", axis_label="% of Population",
                            major_tick_out=8, major_tick_line_alpha=.9,
                            minor_tick_in=4, minor_tick_line_alpha=.9,
                            formatter=NumeralTickFormatter(format="0%")), 'right')

    p.add_tools(HoverTool(
        tooltips=[
            ('Date', '@dt{%F}'),
            ('Forecast Susceptible Population', '@susceptible{0,0}'),
            ('Forecast Deaths', '@deaths{0,0}'),
            ('Forecast Exposures', '@exposed{0,0}'),
            ('Forecast Infectious Population', '@infectious{0,0}'),
            ('Forecast Hospitalizations', '@hospitalized{0,0}'),
            ('Forecast Recoveries', '@recovered{0,0}')
        ],
        formatters={'@dt': 'datetime'},
        mode='vline'
    ))

    p = add_bokeh_footnote(p)
    p = bk_legend(p)

    return p

def bk_postestshare(model_dict):
    df_chart = model_dict['df_hist'][['cases_daily', 'pos_neg_tests_daily']].clip(lower=0)
    df_chart['neg_tests_daily'] = (df_chart['pos_neg_tests_daily'] - df_chart['cases_daily']).clip(lower=0)
    df_chart = df_chart.div(df_chart[['cases_daily','pos_neg_tests_daily']].max(axis=1), axis=0).dropna(how='all')
    df_chart['sevendayavg'] = df_chart['cases_daily'].mask(df_chart['cases_daily'] >= 1.0
                                                           ).rolling(7, min_periods=1).mean()

    p = figure(title='{}: COVID-19 Positivity Rate'.format(model_dict['region_name']),
               x_axis_type="datetime",
               tools='pan,wheel_zoom,box_zoom,zoom_in,zoom_out,reset,save')

    p.varea_stack(['cases_daily', 'neg_tests_daily'],
                  x='dt', source=df_chart,
                  color=['#e5ae38', '#008fd5'],
                  legend_label=['% Positive Tests', '% Negative Tests']
                  )

    p.line(x='dt', y='sevendayavg', source=df_chart, color='#fc4f30', width=4,
           legend_label='Positivity Rate (7-Day Rolling Average)')
    p.legend.location = "top_right"
    p.legend.click_policy = "hide"
    p.toolbar.autohide = True
    p.y_range = Range1d(0, min(1, df_chart['sevendayavg'].max() * 1.1))
    p.yaxis.formatter = NumeralTickFormatter(format="0%")
    p.yaxis.axis_label = '% of Daily Tests'
    p.yaxis.major_tick_out = 5
    p.yaxis.major_tick_line_alpha = .9
    p.yaxis.minor_tick_in = 4
    p.yaxis.minor_tick_line_alpha = .9

    # Setting the second y axis range name and range
    p.extra_y_ranges = {"foo": p.y_range}

    # Adding the second axis to the plot.
    p.add_layout(LinearAxis(y_range_name="foo", axis_label=p.yaxis.axis_label,
                            major_tick_out=5, major_tick_line_alpha=.9,
                            minor_tick_in=4, minor_tick_line_alpha=.9,
                            formatter=p.yaxis.formatter), 'right')

    p.add_tools(HoverTool(
        tooltips=[
            ('Date', '@dt{%F}'),
            ('Daily Positivity Rate', '@cases_daily{0.0%}'),
            ('7-Day Rolling Average Positivity Rate', '@sevendayavg{0.0%}')
        ],
        formatters={'@dt': 'datetime'},
        mode='vline'
    ))

    p = add_bokeh_footnote(p)
    p = bk_legend(p)

    return p

def bk_positivetests(model_dict):
    p = bk_bar_and_line_chart(bar_series=model_dict['df_hist']['cases_daily'].dropna(how='all'),
                       bar_name='# of Positive Tests', bar_color='#e5ae38',
                       line_series=model_dict['df_hist']['cases_daily'].rolling(7, min_periods=1).mean(),
                       line_name='7-Day Rolling Average', yformat='{:0,.0f}',
                       chart_title='{}: Positive COVID-19 Tests Per Day'.format(model_dict['region_name'])
                       )
    return p
