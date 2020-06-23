'''
TO DO:
    * rr:language in pom
    * functions
'''

import pandas
import sys
import os
import shutil
import go_template
import json
import argparse
import re
import gdrive_api

tmpDir = '../tmp/'
templatesDir = '../templates/'
resultDir = '../result/'
supportedLanguages = {'rml', 'r2rml', 'yarrrml'}

def checkFile(path):
    """
    Checks if the input 'path' is an excel file an can be correctly read, returns a boolean
    """
    try:
        data = pandas.ExcelFile(path)
        return True
    except:
        return False

def generateJson(path):
    """
    The input excel file 'path' is translated into JSON format, returns the json
    """
    data = pandas.ExcelFile(path)
    json = {}
    for sheet_ in data.sheet_names:
        sheet = str(sheet_)
        json[sheet] = {}
        json[sheet] = generateJsonCols(data.parse(sheet))
    return json

def generateJsonCols(data):
    """
    Arranges correctly the input pandas dataframe into a json, which is returned as output
    """
    rng = len(data[data.columns[0]])
    result = []
    for row in range(0, rng):
        element = {}
        for col_ in data.columns:
            col = str(col_)
            element[col] = str(data[col][row])
        result.append(element)
    return result

def organizeJson(data):
    """
    Rearranges the data in JSON format into the desired structure, returns the resulting json
    """
    json = {}
    json['Prefixes'] = data['Prefixes']
    json['TriplesMap'] = {}
    for subject in data['Subject']:
        json['TriplesMap'][subject['ID']] = findChilds(data, subject['ID']) 
        json['TriplesMap'][subject['ID']]['Subject'] = subject
        json['TriplesMap'][subject['ID']]['Subject']['SubjectType'] = predicateTypeIdentifier(subject['URI'])
        json['TriplesMap'][subject['ID']]['Source'] = reFormatSource(json['TriplesMap'][subject['ID']]['Source'])
        json['TriplesMap'][subject['ID']]['PredicateObjectMaps']  =  reFormatPredicateObject(json['TriplesMap'][subject['ID']]['PredicateObjectMaps']) 
    json['Functions'] = reFormatFunction(data['Functions'], json)
    return json

def replaceVars(element, type_, datatype_):
    """
    Writes the objects 'element' correctly according to their type 'type_' and datatype 'datatype_', returns the 
    corrected object
    """
    config = json.loads(open(templatesDir + 'config.json').read())
    # Add "" to the constant literal objects in YARRRML
    if(templatesDir == '../templates/yarrrml/' and type_ == 'constant' and datatype_ == 'literal'):
        result = str(config['variable'][type_]['before']) + element + str(config['variable'][type_]['after'])
    # Replace '{' and '}' in all but constant objects according to the config.json file of each language
    elif(type_ != 'constant' and str(config['variable'][type_]['before']) != '{' and str(config['variable'][type_]['after']) != '}'):
        result = element.replace("{", str(config['variable'][type_]['before'])).replace("}", config['variable'][type_]['after'])
    else:
        result = element
    return result
            
def findChilds(data, ID):
    """
    Finds the PredicateObjectMaps and Source in 'data' of the given 'ID' and returns it
    """
    result = {}
    keys = sorted(data.keys())
    keys.remove('Subject')
    keys.remove('Prefixes')
    keys.remove('Functions')

    for key in keys:
        result[key] =  []
        for element in data[key]:
            if(element['ID'] == ID):
                result[key].append(element)
    return result

def reFormatFunction(data_function, data):
    """
    Rearranges the data of functions 'data_function' into the desired structure and adds the source of each function
    with 'data'. The rearranged json is returned.
    """
    result = {}
    for element in data_function:
        element['FunctionID'] = str(element['FunctionID'])[1:-1]
        if element['FunctionID'] not in result.keys():
            result[element['FunctionID']] = {'PredicateObjectMaps':[], 'Source':[]}
            FID = element['FunctionID']

        if element['FunctionID'] == FID:
            if("{" not in str(element['Object']) and "}" not in str(element['Object']) and '<' != str(element['Object'])[0]):
                element['ObjectType'] = 'rr:constant'
            elif(str(element['Object'])[:1] == '{' and str(element['Object'])[-1:] == '}'):
                element['Object'] = str(element['Object'])[1:-1]
                element['ObjectType'] = 'rml:reference'
            elif(str(element['Object'])[:1] == '<' and str(element['Object'])[-1:] == '>'):
                element['Object'] = '<#' + str(element['Object'])[1:]
                element['ObjectType'] = ''
            else:
                print('WARNING: Wrong element in Function', FID)
                element['ObjectType'] = 'rr:constant'
            result[element['FunctionID']]['PredicateObjectMaps'].append(element)

    for fun in result:
        result[fun]['Source'] = find_source(fun, data, result)
        result[fun]['Source']['FunctionID'] = fun

    return(result)

def find_source(function_key, data, functions):
    """
    Finds the source of the 'function_key' in 'data' or in 'functions', and returns it
    """
    for tm in data['TriplesMap']:
        if len(data['TriplesMap'][tm]['PredicateObjectMaps']['Function']) != 0:
            for fun in data['TriplesMap'][tm]['PredicateObjectMaps']['Function']:
                if fun['Object'] == function_key:
                    return(data['TriplesMap'][tm]['Source'])
    for fun in functions:
        if len(functions[fun]['Source']) != 0:
            for element in functions[fun]['PredicateObjectMaps']:
                if element['Object'][2:-1] == function_key:
                    return(functions[fun]['Source'])

def reFormatPredicateObject(data):
    """
    Rearranges the json contained in 'data' for the Triple Object Maps, and returns it
    """
    result = {'Join':[], 'Template':[], 'Function':[], 'ReferenceObject':[], 'ConstantObject':[]}
    nullValues =  {'', 'NaN', ' ', 'nan', 'NAN'} 
    for element in data:
        element['PredicateType'] = predicateTypeIdentifier(element['Predicate'])
        element['DataType'] = dataTypeIdentifier(element['DataType'])
        element['TermType'], element['isIRI'] = termTypeIdentifier(element['Object'], element['DataType'])

        # Populate Join key
        if(str(element['Object'])in nullValues and str(element['InnerRef']) not in nullValues and str(element['OuterRef']) not in nullValues):
            element['ObjectType'] = 'reference'
            result['Join'].append(element)
        # Populate Function key
        elif(str(element['Object'])[:1] == '<' and str(element['Object'])[-1:] == '>'):
            element['ObjectType'] = 'reference' 
            element['Object'] = str(element['Object'])[1:-1]
            result['Function'].append(element)
        # Populate Constant key
        elif("{" not in str(element['Object']) and "}" not in str(element['Object'])):
            element['ObjectType'] = 'constant'
            result['ConstantObject'].append(element)
        # Populate Template key
        elif(bool(re.search("{.+}.+", str(element['Object']))) or bool(re.search(".+{.+}", str(element['Object'])))):
            element['ObjectType'] = 'template'
            result['Template'].append(element)
        # Populate Reference key when none of the conditions above are fulfilled
        else:
            element['ObjectType'] = 'reference'
            result['ReferenceObject'].append(element)
    return result

def dataTypeIdentifier(element):
    """
    Identifies the datatype of the object 'element' and returns it
    """
    # Load the json with some xsd datatypes predefined
    dataTypes = json.loads(open('datatypes.json').read())
    for key in dataTypes.keys():
        if element.lower().strip() in dataTypes[key]:
            return key
    print('WARNING: datatype not recognized (' + element + '), check XSD datatypes')
    return element

def termTypeIdentifier(element, dataType):
    """
    Identifies the termtype of the object 'element' based on itself and its datatype 'dataType' and returns it 
    """
    if(len(str(element).split(":")) == 2 or "http" in str(element) or dataType == "anyURI"):
        return 'IRI', '~iri'
    else: 
        return 'literal', ''
        
def predicateTypeIdentifier(element):
    """
    Identifies the type of the predicate, distinguishing between constant, reference and template, and returns it
    """
    # For constant
    if(len(str(element).split(":")) == 2 and "{" not in str(element) and "}" not in str(element)):
        return 'constant'
    # For reference 
    elif(str(element)[:1] == '{' and str(element)[-1:] == '}' and str(element).split(" ")  == 1):
        return 'reference'
    # For template
    elif(bool(re.search("{.+}.+", str(element))) or bool(re.search(".+{.+}", str(element)))):
        return 'template'
    # Constant when not recognized
    else:
        print("WARNING: type not identified for predicate '" + element + "', 'constant' assigned")
        return 'constant'
 
def reFormatSource(data):
    """
    Rearranges the format of the 'Source' sheet in 'data' and returns it
    """
    result = {}
    for element in data:
        if(element['Feature'].lower() == 'source'):
            result['Source'] = str(element['Value'])
        elif(element['Feature'].lower() == 'format'):
            result['Format'] = str(element['Value'])
        elif(element['Feature'].lower() == 'iterator'):
            result['Iterator'] = str(element['Value'])
        elif(element['Feature'].lower() == 'table'):
            result['Source'] = str(element['Value'])
        else:
            print("ERROR: " + element + " feature not recognized. The recognized values for the \
                column 'Feature' in 'Source' are 'source', 'format', 'iterator' and 'table'")
            sys.exit()
    if('Iterator' not in result.keys()):
            result['Iterator'] = ''
    result['ID'] = data[0]['ID']
    return result

def writeValues(data, path):
    """
    Redirects the data to the specific functions to write the 'data' into the file 'path'
    """
    if not os.path.isdir(tmpDir):
        os.mkdir(tmpDir)

    writePrefix(data,path)
    for triplesmap in data['TriplesMap']:
        writeTriplesMap(triplesmap, path)
        writeSubject(data['TriplesMap'][triplesmap]['Subject'], path)
        writeSource(data['TriplesMap'][triplesmap]['Source'], path)       
        writePredicateObjects(data['TriplesMap'][triplesmap]['PredicateObjectMaps'], path)
    
    # Functions implemented only in RML
    if templatesDir == '../templates/rml/':
        for function in data['Functions']:
            writeFunctionMap(function, path)
            writeFunctionPOM(data['Functions'][function]['PredicateObjectMaps'], path)
            writeFunctionSource(data['Functions'][function]['Source'], path)
    
    
def writePrefix(data, path):
    """
    Writes the prefixes temporal file from the template with the information in 'data' into the path 'path'
    """
    for prefix in data['Prefixes']:
        f = open(path + 'Prefixes.yml', 'a+')
        for element in prefix:
            if element == 'Prefix' and ':' in str(prefix[element]):
                prefix[element] = re.sub(':', '', str(prefix[element]))
            f.write(str(element) + ': ' + str(prefix[element]) + '\n')
        f.close()
        go_template.render_template(templatesDir + 'Prefixes.tmpl',tmpDir + 'Prefixes.yml', tmpDir + 'Prefixes.txt')
        writeResult('', 'Prefixes')

def writeTriplesMap(data, path):
    """
    Writes the triples map temporal file from the template with the information in 'data' into the path 'path'
    """
    f = open(path + 'TriplesMap.yml', 'a+')
    f.write('ID: ' + str(data) + '\n')
    f.close()
    go_template.render_template(templatesDir + 'TriplesMap.tmpl',tmpDir + 'TriplesMap.yml', tmpDir + 'TriplesMap.txt')
    writeResult(str(data), 'TriplesMap')

def writePredicateObjects(data, path):
    """
    Writes the predicateObjectMaps temporal file from the template with the information in 'data' into the path 'path'
    """
    for key in data:
        if(len(data[key]) > 0):
            for predicateObjects in data[key]:
                f = open(path + key + '.yml', 'a+')
                predicateObjects['Object'] = replaceVars(str(predicateObjects['Object']), str(predicateObjects['ObjectType']), str(predicateObjects['TermType']))
                predicateObjects['Predicate'] = replaceVars(str(predicateObjects['Predicate']), str(predicateObjects['PredicateType']), 'nan')
                if( 'InnerRef' in predicateObjects.keys() and 'OuterRef' in predicateObjects.keys()):
                    predicateObjects['InnerRef'] = replaceVars(str(predicateObjects['InnerRef']), 'join_condition', 'nan')
                    predicateObjects['OuterRef'] = replaceVars(str(predicateObjects['OuterRef']), 'join_condition', 'nan')

                for element in predicateObjects:
                    f.write(str(element) + ': \'' + predicateObjects[element] + '\'\n')
                f.close()
                go_template.render_template(templatesDir + key + '.tmpl',tmpDir + key + '.yml', tmpDir + key + '.txt')
                writeResult(data[key][0]['ID'], key)

def writeSource(data, path):
    """
    Writes the source temporal file from the template with the information in 'data' into the path 'path'
    """
    f = open(path + 'Source.yml', 'a+')
    config  = json.loads(open(templatesDir + 'config.json').read())
    if(data['Iterator'] != ''):
        data['Iterator'] = str(config['iterator']['before']) + str(data['Iterator']) + str(config['iterator']['after'])
    for element in data:
        f.write(str(element) + ': \'' + data[element] + '\'\n')
    f.close()
    go_template.render_template(templatesDir + 'Source.tmpl',tmpDir + 'Source.yml', tmpDir + 'Source.txt')
    writeResult(data['ID'], 'Source')

   
def writeSubject(data, path):
    """
    Writes the subject temporal file from the template with the information in 'data' into the path 'path'
    """
    f = open(path + 'Subject.yml', 'a+')
    data['URI'] = replaceVars(data['URI'], data['SubjectType'], 'nan')
    for element in data:
        f.write(element + ': ' + data[element] + '\n')
    f.close()
    go_template.render_template(templatesDir + 'Subject.tmpl',tmpDir + 'Subject.yml', tmpDir + 'Subject.txt')
    writeResult(data['ID'], 'Subject')

def writeFunctionMap(data, path):
    """
    Writes the function map temporal file from the template with the information in 'data' into the path 'path'
    """
    f = open(path + 'FunctionMap.yml', 'a+')
    f.write('FunctionID: ' + str(data) + '\n')
    f.close()
    go_template.render_template(templatesDir + 'FunctionMap.tmpl', tmpDir + 'FunctionMap.yml', tmpDir + 'FunctionMap.txt')
    writeResult(str(data), 'FunctionMap')

def writeFunctionSource(data, path):
    """
    Writes the source of function temporal file from the template with the information in 'data' into the path 'path'
    """
    f = open(path + 'FunctionSource.yml', 'a+')
    config  = json.loads(open(templatesDir + 'config.json').read())
    if(data['Iterator'] != ''):
        data['Iterator'] = str(config['iterator']['before']) + str(data['Iterator']) + str(config['iterator']['after'])
    for element in data:
        f.write(str(element) + ': \'' + data[element] + '\'\n')
    f.close()
    go_template.render_template(templatesDir + 'FunctionSource.tmpl',tmpDir + 'FunctionSource.yml', tmpDir + 'FunctionSource.txt')
    writeResult(data['FunctionID'], 'FunctionSource')

def writeFunctionPOM(data, path):
    """
    Writes the predicateObjectMaps of function temporal file from the template with the information in 'data' into the path 'path'
    """
    for pom in data:
        f = open(path + 'FunctionPOM.yml', 'a+')
        if pom['Predicate'] != 'fno:executes' and str(pom['Object'])[0] != '<':
            pom['Object'] = '\"' + pom['Object'] + '\"'
        for element in pom:
            f.write(str(element) + ': \'' + pom[element] + '\'\n')
        f.close()
        go_template.render_template(templatesDir + 'FunctionPOM.tmpl', tmpDir + 'FunctionPOM.yml', tmpDir + 'FunctionPOM.txt')
        writeResult(pom['FunctionID'], 'FunctionPOM')

def writeResult(ID, name):
    """
    Writes the temporal files assigning ID and names for the different parts of the mapping
    """
    delete = open(tmpDir + name + '.txt', 'r')
    final = open(resultDir + ID + '.' + name + '.' + 'result.txt', 'a+')
    final.writelines(delete.readlines())
    delete.close()
    final.close()
    try:
        os.remove(tmpDir + name + '.txt')
        os.remove(tmpDir + name + '.yml')
    except:
        pass

def writeFinalFile(path_, idTMList, idFList):
    """
    Gathers all the temporal files identified with 'idTMList' and 'idFList' and writes
    it in the final mapping file in 'path_'
    """
    data = json.loads(open(templatesDir  + 'structure.json').read())
    config = json.loads(open(templatesDir + 'config.json').read())
    path = path_ + '.' +  str(config['extension'])
    recursiveWrite(0,data['unique'], path, '')
    for id_ in idTMList:
        recursiveWrite(0, data['variable'], path, id_)
    for id_ in idFList:
        recursiveWrite(0, data['variable'], path, id_)

def recursiveWrite(tabs, parent, finalFile, id_):
    """
    Writes the temporal files in one recursively
    """
    for data in range(0, len(parent)):
        file_ = resultDir + id_ + '.' + parent[data]['file'] + '.result.txt'
        config = json.loads(open(templatesDir + 'config.json').read())
        exists = os.path.isfile(file_)
        if(exists):
            f = open(file_, 'r')    
            final = open(finalFile, 'a+')
            if(str(parent[data]["before"]) != ""):
                final.write(parent[data]["before"] + '\n')
            for line in f.readlines():
                final.write(' ' * int(config['tab']['size']) * tabs + str(line))
            f.close()
            os.remove(file_)
            final.close()
            if(len(parent[data]['childs']) > 0):
                recursiveWrite(parent[data]['tabs'], parent[data]['childs'], finalFile, id_)
            if(str(parent[data]["after"]) != ""):
                final = open(finalFile, 'a+')
                final.write(parent[data]["after"] + '\n')
                final.close()

def cleanDir(path):
    """
    Cleans the results directory
    """
    Dir = os.listdir(path)
    for f in Dir:
        os.remove(path + f)

def generateMapping(inputFile):
    """
    General function with the flow of the script to generate and organize the JSON file with the data from 
    'inputFile', and write it in the mapping file
    """
    if os.path.isdir(resultDir):
        cleanDir(resultDir)
    else:
        os.mkdir(resultDir)
    
    fileName = re.findall(r'\/(\w+)\.',inputFile)
    try:
        json = generateJson(inputFile)
        #print("First JSON: ")
        #print(str(json).replace('\'', '\"'))
        json = organizeJson(json)
        #print("Second JSON: ")
        #print(str(json).replace('\'', '\"'))
        # sys.exit()
    except KeyError:
        print("ERROR: The spreadsheet template is not correct. Check the sheet and column names are correct.")
        sys.exit()

    writeValues(json,tmpDir)
    writeFinalFile(resultDir + fileName[0], json['TriplesMap'].keys(), json['Functions'].keys())
    #print(json)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--input_file", required=False, help="Input excel file")
    parser.add_argument("-l", "--language", required=True, help=("Supported Languages: " + str(supportedLanguages)))
    args = parser.parse_args()
    inputFile = ''

    # Local file
    if(checkFile(args.input_file)):
        inputFile = str(args.input_file)
    # Google Spreadsheet file
    elif(str(args.input_file)[-4:] == '.ini'):
        gdrive_api.download_sheet(args.input_file)
        if checkFile('../data/drive_sheet.xlsx'):
            inputFile = '../data/drive_sheet.xlsx'
        else:
            print("ERROR: The downloaded document is not a spreadsheet")
            sys.exit()
    else:
        print("WARNING: Not input file selected or not valid. Using the default xlsx file (data/default.xlsx)")
        inputFile = '../data/default.xlsx'

    if(args.language.lower() not in supportedLanguages):
        print("ERROR: The selected Language is not supported by the moment.")
        print("Suporteds Languages: " + str(supportedLanguages))
        sys.exit()
    else:
        global templatesDir
        templatesDir += args.language.lower() + "/"
        print('Generating mapping file')
        generateMapping(inputFile)
        print("Your mapping file is in ../result/")

if __name__ == '__main__':
    main()
    

