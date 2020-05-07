import pandas as pd
import numpy as np
import os, time, stat, io
from scipy.stats import gamma, norm
from sklearn.linear_model import LinearRegression
from coronita_chart_helper import *

def daily_cohort_model(cohort_strt, d_to_fore, covid_params, E_0, I_0=0):
    t = np.linspace(0, int(d_to_fore) - 1, int(d_to_fore))

    E = [E_0]
    I = [I_0]
    H = [0]
    ICU = [0]
    R = [0]
    D = [0]

    for t_ in t[:-1]:

        #### PROBABILITY DISTRIBUTIONS FOR FLOWS ####
        prob_dI_t = gamma.pdf(t_, covid_params['d_incub'])

        prob_mild_dR_t = (1 - covid_params['hosp_rt']) * gamma.pdf(t_, covid_params['d_infect'] + covid_params['d_incub'])

        prob_H_inflow_fromE0_t = covid_params['hosp_rt'] * gamma.pdf(t_, covid_params['d_to_hosp'] + covid_params['d_incub'])
        prob_H_inflow_fromI0_t = covid_params['hosp_rt'] * gamma.pdf(t_, covid_params['d_to_hosp'] / 2, scale=2)

        prob_sev_dR_t = ( (covid_params['hosp_rt'] - covid_params['mort_rt'])
                          * gamma.pdf(t_, (covid_params['d_incub'] + covid_params['d_in_hosp'] + covid_params['d_to_hosp']) / 2, scale=2) )

        prob_dD_t = covid_params['mort_rt'] * gamma.pdf(t_, (covid_params['d_til_death'] + covid_params['d_incub']) / 1, scale=1)
        #############################################

        ############## FLOW ACCOUNTING ##############
        # Change in Exposed Population
        dE = -1 * min(prob_dI_t * E[0], E[-1])

        # Hospital Outflows, limited to be no more than hospital capacity
        d_hosp_outflow = -1 * min((prob_sev_dR_t * (E[0] + I[0])
                                   + H[0] * (prob_sev_dR_t / (covid_params['hosp_rt'] - covid_params['mort_rt'])) * (1 - covid_params['mort_rt'] / covid_params['hosp_rt']))
                                  + (prob_dD_t * (E[0] + I[0])
                                     + H[0] * (prob_dD_t / covid_params['mort_rt']) * covid_params['mort_rt'] / covid_params['hosp_rt']),
                                  H[-1])

        if (prob_sev_dR_t + prob_dD_t) > 0:
            # Severe Recoveries - Component of Hospital Outflows
            d_sevR = (-1 * prob_sev_dR_t * d_hosp_outflow) / (prob_sev_dR_t + prob_dD_t)

            # Deaths - Component of Hospital Outflows
            dD = (-1 * prob_dD_t * d_hosp_outflow) / (prob_sev_dR_t + prob_dD_t)
        else:
            # Severe Recoveries - Component of Hospital Outflows
            d_sevR = 0.
            # Deaths - Component of Hospital Outflows
            dD = 0.

        # New Hospital Admittances
        d_hosp_admits = prob_H_inflow_fromE0_t * E[0] + prob_H_inflow_fromI0_t * I[0]

        # Infectious Inflows
        dI_inflow = -1 * dE

        # Mild Recoveries
        d_mildR = min(prob_mild_dR_t * (E[0] + I[0]), I[-1] + dI_inflow - d_hosp_admits)

        # Change in Recovered Population
        dR = d_mildR + d_sevR

        # Change in Hospitalized Population
        dH = d_hosp_admits + d_hosp_outflow

        # Infectious Outflows
        dI_outflow = d_mildR + d_hosp_admits

        # Net change in Infectious Population
        dI = dI_inflow - dI_outflow

        if round(dI_inflow - dI_outflow) < round(-1 * I[-1]):
            print('dI_inflow', dI_inflow)
            print('dI_outflow', dI_outflow)
            print('round(dI_inflow - dI_outflow)', round(dI_inflow - dI_outflow))
            print('I[-1]', I[-1])
            raise Exception(cohort_strt, 'Daily Cohort Infectious Net Outflows are greater than Infectious Population')
            #############################################

        E.append(E[-1] + dE)
        I.append(I[-1] + dI)
        R.append(R[-1] + dR)
        H.append(H[-1] + dH)
        D.append(D[-1] + dD)
    df_out = pd.DataFrame(np.stack([E, I, R, H, D]).T,
                          columns=['exposed', 'infectious', 'recovered', 'hospitalized', 'deaths'],
                          index=pd.date_range(cohort_strt,
                                              cohort_strt + pd.Timedelta(days=d_to_fore - 1)))
    df_out['icu'] = df_out['hospitalized'].mul(covid_params['icu_rt'])
    df_out['vent'] = df_out['hospitalized'].mul(covid_params['icu_rt'] * covid_params['vent_rt'])
    df_out.index = pd.DatetimeIndex(df_out.index).normalize()
    df_out.index.name = 'dt'
    df_out.columns.name = 'metric'

    return df_out


def seir_model_cohort(start_dt, model_dict, exposed_0=100, infectious_0=100):
    suspop = [model_dict['tot_pop'] - exposed_0 - infectious_0]
    next_infectious = infectious_0
    _gamma = 1 / model_dict['covid_params']['d_infect']

    t = np.linspace(0, model_dict['d_to_forecast'], model_dict['d_to_forecast'] + 1)

    df_all_cohorts = pd.DataFrame()
    df_all_cohorts.columns.name = 'cohort_dt'

    r_t = pd.Series(np.nan, index=pd.date_range(start_dt,
                                                start_dt + pd.Timedelta(days=model_dict['d_to_forecast']) ) )
    r_t = r_t.fillna(model_dict['df_rts']['rt_joint_est']).fillna(method='bfill').fillna(method='ffill')
    last_r = r_t.iloc[0]

    for t_ in t[:-1]:
        cohort_strt = start_dt + pd.Timedelta(days=t_)
        this_r = r_t.loc[cohort_strt]
        beta = this_r * _gamma

        d_to_fore = t[-1] - t_ + 1

        if this_r != last_r:
            last_r = this_r

        if t_ == 0:
            dS = 0

            df_daily_cohort = daily_cohort_model(
                cohort_strt, d_to_fore,
                model_dict['covid_params'], E_0=exposed_0, I_0=infectious_0)

            df_all_cohorts[cohort_strt] = df_daily_cohort.stack()

            df_daily_cohort_scalar = daily_cohort_model(
                cohort_strt, d_to_fore,
                model_dict['covid_params'], E_0=1e6, I_0=0).reset_index(drop=True)

        else:
            dS = -1 * min(beta * suspop[-1] * next_infectious / model_dict['tot_pop'], suspop[-1])

            df_daily_cohort = dS * -1 * df_daily_cohort_scalar.iloc[:int(d_to_fore)] / 1e6

            df_daily_cohort.index = pd.date_range(cohort_strt,
                                                  cohort_strt + pd.Timedelta(days=d_to_fore - 1))
            df_all_cohorts[cohort_strt] = df_daily_cohort.stack()
            # print(cohort_strt, ' rt: ', this_r)

        d_cohort_totpop_std = round(df_daily_cohort[
                                        ['exposed', 'deaths', 'hospitalized', 'infectious', 'recovered']
                                    ].dropna().sum(axis=1).std(), 3)

        if d_cohort_totpop_std != 0.0:
            print(cohort_strt, d_cohort_totpop_std)
            display(df_daily_cohort)
            raise Exception('Daily Cohort total population varies significantly')

        df_agg = df_all_cohorts.sum(axis=1).unstack()
        df_agg.index = pd.DatetimeIndex(df_agg.index).normalize()
        next_infectious = df_agg.loc[cohort_strt, 'infectious']
        next_suspop = suspop[-1] + dS
        suspop.append(next_suspop)

        totpopchk = df_agg.loc[cohort_strt, ['exposed', 'infectious', 'recovered', 'hospitalized', 'deaths']].sum()

        if (round(totpopchk + suspop[-1]) != round(model_dict['tot_pop'])):
            display(df_all_cohorts)
            display(df_all_cohorts.sum(axis=1).unstack())
            print(cohort_strt)
            print('totpop: ', round(model_dict['tot_pop']))
            print('dS ', dS)
            print('sum of df_agg', totpopchk)
            print('suspop[-1]', suspop[-1])
            print('sum of both', round(totpopchk + suspop[-1]))
            raise Exception('Agg total population varies significantly')

    df_agg = df_all_cohorts.sum(axis=1).unstack()
    df_agg.index = pd.DatetimeIndex(df_agg.index).normalize()

    s_suspop = pd.Series(suspop, index=pd.date_range(
        start_dt - pd.Timedelta(days=1),
        start_dt + pd.Timedelta(days=model_dict['d_to_forecast'] - 1)))

    df_agg['susceptible'] = pd.Series(s_suspop)

    return df_agg.dropna(), df_all_cohorts

def model_find_start(start_dt, model_dict, exposed_0=100, infectious_0=100):
    from sklearn.metrics import mean_squared_error

    this_guess = pd.Timestamp(start_dt)
    last_guess = this_guess
    rmses = pd.Series(dtype='float64')
    change_in_error = -1

    while change_in_error < 0:
        df_agg, df_all_cohorts = seir_model_cohort(this_guess, model_dict, exposed_0, infectious_0)
        true_hosps = model_dict['df_hist']['hosp_concur'].dropna()
        pred_hosps = df_agg['hospitalized'].loc[true_hosps.index]
        rmses.loc[this_guess] = np.sqrt(mean_squared_error(true_hosps, pred_hosps))

        if last_guess != this_guess:
            change_in_error = rmses.loc[this_guess] - rmses.loc[last_guess]

        last_guess = this_guess
        if true_hosps.sub(pred_hosps).mean() < 0:
            this_guess = this_guess + pd.Timedelta(days=1)
        else:
            this_guess = this_guess - pd.Timedelta(days=1)

    df_agg, df_all_cohorts = seir_model_cohort(rmses.idxmin(), model_dict, exposed_0, infectious_0)
    return df_agg, df_all_cohorts

def est_rt(df_input, lookback, d_infect, offset_days):
    _gamma = 1 / d_infect
#     df_beta = df_input.pct_change().rolling(lookback,center=True).mean().add(_gamma)
    df_beta = df_input.rolling(lookback,
        win_type='gaussian',
        min_periods=3,
        center=False).mean(std=2).pct_change().rolling(lookback,center=False
                                                     ).mean().add(_gamma)
    df_rt = df_beta.div(_gamma)
    df_rt.index = (df_rt.index - pd.Timedelta(days=(offset_days + (lookback-2)))).normalize()
    df_rt = df_rt.dropna().clip(lower=0.0)
    return df_rt

def est_all_rts(model_dict):
    df_rts = pd.DataFrame(index=model_dict['df_hist']['cases_daily'].index)

    if 'deaths_daily' in model_dict['df_hist'].columns:
        df_rts['rt_deaths_daily'] = est_rt(model_dict['df_hist']['deaths_daily'],
                                           14,
                                           model_dict['covid_params']['d_infect'],
                                           model_dict['covid_params']['d_incub'] + model_dict['covid_params'][
                                               'd_til_death'] / 2
                                           )

    if 'hosp_concur' in model_dict['df_hist'].columns:
        df_rts['rt_hosp_concur'] = est_rt(model_dict['df_hist']['hosp_concur'],
                                          7,
                                          model_dict['covid_params']['d_infect'],
                                          (model_dict['covid_params']['d_incub']
                                           + model_dict['covid_params']['d_to_hosp']
                                           + model_dict['covid_params']['d_in_hosp'] / 2
                                           ))

    if 'hosp_admits' in model_dict['df_hist'].columns:
        df_rts['rt_hosp_admits'] = est_rt(model_dict['df_hist']['hosp_admits'],
                                          7,
                                          model_dict['covid_params']['d_infect'],
                                          (model_dict['covid_params']['d_incub']
                                           + model_dict['covid_params']['d_to_hosp']
                                           ))

    if 'cases_daily' in model_dict['df_hist'].columns:
        df_rts['rt_cases_daily'] = est_rt(model_dict['df_hist']['cases_daily'],
                                          7,
                                          model_dict['covid_params']['d_infect'],
                                          (model_dict['covid_params']['d_incub']
                                          ))

    if ('cases_daily' in model_dict['df_hist'].columns) and ('pos_neg_tests_daily' in model_dict['df_hist'].columns):
        df_rts['rt_pos_test_share_daily'] = est_rt(
            model_dict['df_hist']['cases_daily'].div(model_dict['df_hist']['pos_neg_tests_daily']),
            7,
            model_dict['covid_params']['d_infect'],
            (model_dict['covid_params']['d_incub']
            ))

    primary_rts = ['rt_deaths_daily', 'rt_hosp_concur', 'rt_hosp_admits']
    avail_prim_rts = [col for col in df_rts.columns if col in primary_rts]
    df_rts['rt_primary_mean'] = df_rts[avail_prim_rts].mean(axis=1).rolling(7,
        win_type='gaussian',
        min_periods=3,
        center=True).mean(std=2)

    secondary_rt = 'rt_pos_test_share_daily' if 'rt_pos_test_share_daily' in df_rts.columns else 'rt_cases_daily'
    secondary_index = pd.Series(1.0,
                                index=pd.date_range(df_rts['rt_primary_mean'].last_valid_index(),
                                                    df_rts[secondary_rt].last_valid_index()))
    secondary_index = secondary_index.add(df_rts[secondary_rt].loc[secondary_index.index].pct_change(),
                                          fill_value=0)
    secondary_index = secondary_index.cumprod()
    df_rts['rt_secondary_est'] = secondary_index.mul(df_rts['rt_primary_mean'].dropna().iloc[-1])

    df_rts['rt_joint_est'] = df_rts['rt_primary_mean'].fillna(df_rts['rt_secondary_est'])

    return df_rts

def make_model_dict_state(state_code, abbrev_us_state, df_census, df_st_testing_fmt, covid_params, d_to_forecast = 75):
    model_dict = {}

    model_dict['region_code'] = state_code
    model_dict['region_name'] = abbrev_us_state[model_dict['region_code']]
    model_dict['tot_pop'] = df_census.loc[(df_census.SUMLEV == 40)
                                                  & (df_census.state == model_dict['region_code']),
                                                  'pop2019'].values[0]

    model_dict['df_hist'] = pd.DataFrame()

    if df_st_testing_fmt['deaths'][model_dict['region_code']].dropna().shape[0] > 14:
        model_dict['df_hist']['deaths_tot'] = df_st_testing_fmt['deaths'][model_dict['region_code']]
        model_dict['df_hist']['deaths_daily'] = model_dict['df_hist']['deaths_tot'].diff()

    if df_st_testing_fmt['hospitalizedCurrently'][model_dict['region_code']].dropna().shape[0] > 14:
        model_dict['df_hist']['hosp_concur'] = df_st_testing_fmt['hospitalizedCurrently'][model_dict['region_code']]

    if df_st_testing_fmt['hospitalizedIncrease'][model_dict['region_code']].dropna().shape[0] > 14:
        model_dict['df_hist']['hosp_admits'] = df_st_testing_fmt['hospitalizedIncrease'][model_dict['region_code']]
    model_dict['df_hist']['cases_tot'] = df_st_testing_fmt['cases'][model_dict['region_code']]
    model_dict['df_hist']['cases_daily'] = model_dict['df_hist']['cases_tot'].diff()
    model_dict['df_hist']['pos_neg_tests_tot'] = df_st_testing_fmt['posNeg'][model_dict['region_code']]
    model_dict['df_hist']['pos_neg_tests_daily'] = model_dict['df_hist']['pos_neg_tests_tot'].diff()

    model_dict['covid_params'] = covid_params

    model_dict['df_rts'] = est_all_rts(model_dict)

    model_dict['covid_params']['basic_r0'] = model_dict['df_rts']['rt_joint_est'].iloc[0]

    model_dict['d_to_forecast'] = int(d_to_forecast)

    return model_dict
